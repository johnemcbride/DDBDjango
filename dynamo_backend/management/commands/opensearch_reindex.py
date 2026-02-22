"""
Management command: opensearch_reindex
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Rebuild (or build from scratch) the OpenSearch indices by scanning every
registered Django model's DynamoDB table and indexing all items.

Usage
─────
    # Reindex everything
    python manage.py opensearch_reindex

    # Reindex specific app labels or app_label.ModelName pairs
    python manage.py opensearch_reindex demo_app
    python manage.py opensearch_reindex demo_app.Post demo_app.Author

    # Wipe indices first then rebuild
    python manage.py opensearch_reindex --reset

    # Dry-run: print what would be indexed without touching OpenSearch
    python manage.py opensearch_reindex --dry-run
"""

from __future__ import annotations

import time
from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


# Models that live entirely inside Django internals and should not be
# user-exported to OpenSearch.
_SKIP_APP_LABELS = frozenset(
    {
        "contenttypes",
        "sessions",
        "auth",
        "admin",
    }
)


class Command(BaseCommand):
    help = "Rebuild OpenSearch indices from DynamoDB tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "targets",
            nargs="*",
            metavar="app_or_model",
            help=(
                "Optional list of app labels (e.g. demo_app) or "
                "app_label.ModelName pairs to reindex. "
                "Defaults to all user-defined models."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            default=False,
            help="Delete and recreate each OpenSearch index before reindexing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be indexed without actually writing to OpenSearch.",
        )
        parser.add_argument(
            "--db",
            default="default",
            help="Django database alias to use (default: default).",
        )

    # ──────────────────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        from dynamo_backend import opensearch_sync

        dry_run: bool = options["dry_run"]
        reset: bool = options["reset"]
        db_alias: str = options["db"]
        targets: list[str] = options["targets"]

        # ── Resolve which models to reindex ───────────────────────────────────
        if targets:
            model_list = self._resolve_targets(targets)
        else:
            model_list = [
                m
                for m in apps.get_models()
                if m._meta.app_label not in _SKIP_APP_LABELS
                and not m._meta.abstract
                and not m._meta.proxy
            ]

        if not model_list:
            raise CommandError("No models matched the given targets.")

        # ── Probe OpenSearch ──────────────────────────────────────────────────
        if not dry_run:
            client = opensearch_sync._get_client()
            if client is None:
                raise CommandError(
                    "OpenSearch is unavailable — check OPENSEARCH_ENDPOINT_URL "
                    "and ensure LocalStack is running with SERVICES=dynamodb,opensearch."
                )

        # ── Table prefix for this DB alias ────────────────────────────────────
        conn = connections[db_alias]
        prefix = conn.settings_dict.get("OPTIONS", {}).get("table_prefix", "")

        # ── Reindex each model ────────────────────────────────────────────────
        total_docs = 0
        total_start = time.perf_counter()

        for model in model_list:
            table_name = prefix + model._meta.db_table
            label = f"{model._meta.app_label}.{model._meta.object_name}"

            if reset and not dry_run:
                self._reset_index(opensearch_sync, table_name, label)

            count = self._reindex_model(
                model, table_name, label, db_alias, dry_run, opensearch_sync
            )
            total_docs += count

        elapsed = time.perf_counter() - total_start
        mode = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}Reindex complete — "
                f"{total_docs} document(s) across {len(model_list)} model(s) "
                f"in {elapsed:.2f}s"
            )
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve_targets(self, targets: list[str]):
        model_list = []
        for t in targets:
            if "." in t:
                app_label, model_name = t.split(".", 1)
                try:
                    model_list.append(apps.get_model(app_label, model_name))
                except LookupError:
                    raise CommandError(f"Unknown model: {t}")
            else:
                app_models = apps.get_app_config(t).get_models()
                model_list.extend(
                    m
                    for m in app_models
                    if not m._meta.abstract and not m._meta.proxy
                )
        return model_list

    def _reset_index(self, opensearch_sync, table_name: str, label: str):
        idx = opensearch_sync._index_name(table_name)
        client = opensearch_sync._get_client()
        if client is None:
            return
        try:
            if client.indices.exists(index=idx):
                client.indices.delete(index=idx)
                opensearch_sync._known_indices.discard(idx)
                self.stdout.write(f"  Deleted index {idx}")
        except Exception as exc:
            self.stderr.write(
                self.style.WARNING(f"  Could not delete index {idx}: {exc}")
            )

    def _reindex_model(
        self, model, table_name: str, label: str, db_alias: str, dry_run: bool, opensearch_sync
    ) -> int:
        self.stdout.write(f"Reindexing {label} → {table_name} ...", ending="")
        self.stdout.flush()

        t0 = time.perf_counter()
        pk_attname = model._meta.pk.attname

        # Full DynamoDB scan via boto3 (bypasses Django ORM cursor to avoid
        # hitting the scan_limit / pagination wrapper).
        try:
            conn = connections[db_alias]
            resource = conn.get_dynamodb_resource()
            table = resource.Table(table_name)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f" SKIP ({exc})"))
            return 0

        items_scanned = 0
        kwargs: dict = {}

        try:
            if not dry_run:
                opensearch_sync.ensure_index(table_name)

            while True:
                resp = table.scan(**kwargs)
                batch = resp.get("Items", [])

                if not dry_run and batch:
                    from opensearchpy.helpers import bulk  # type: ignore[import]
                    actions = []
                    for item in batch:
                        pk = item.get(pk_attname)
                        if pk is None:
                            continue
                        doc = {k: _safe_value(v) for k, v in item.items()}
                        actions.append(
                            {
                                "_op_type": "index",
                                "_index": opensearch_sync._index_name(table_name),
                                "_id": str(pk),
                                **doc,
                            }
                        )
                    if actions:
                        client = opensearch_sync._get_client()
                        if client:
                            bulk(client, actions, raise_on_error=False)

                items_scanned += len(batch)

                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f" ERROR: {exc}"))
            return items_scanned

        elapsed = time.perf_counter() - t0
        mode = " [dry-run]" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f" {items_scanned} docs in {elapsed:.2f}s{mode}")
        )
        return items_scanned


def _safe_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [_safe_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _safe_value(vv) for k, vv in v.items()}
    if isinstance(v, set):
        return [_safe_value(x) for x in v]
    return v
