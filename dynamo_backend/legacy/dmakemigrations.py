"""
management command:  python manage.py dmakemigrations [app_label ...]

Detects changes to DynamoModel definitions and generates new
dynamo migration files.

Examples
--------
    python manage.py dmakemigrations
    python manage.py dmakemigrations demo_app
    python manage.py dmakemigrations --name describe_changes
    python manage.py dmakemigrations --check       # exit 1 if changes detected
    python manage.py dmakemigrations --dry-run     # print without writing
"""

from __future__ import annotations

import os
from typing import List, Optional

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError

from dynamo_backend.migration_autodetector import current_model_state, detect_changes
from dynamo_backend.migration_loader import MigrationLoader
from dynamo_backend.migration_writer import MigrationWriter


class Command(BaseCommand):
    help = "Create new dynamo migration files for DynamoModel changes."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="app_label",
            nargs="*",
            help="Optional app label(s) to generate migrations for.",
        )
        parser.add_argument(
            "--name", "-n",
            default=None,
            help="Name suffix for the migration file (default: 'auto').",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with a non-zero status if any changes are detected.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the migration file(s) without writing them.",
        )

    def handle(self, *args, **options):
        app_labels: List[str] = list(args) or [
            cfg.label for cfg in django_apps.get_app_configs()
        ]
        name_suffix: str = options.get("name") or "auto"
        check_only: bool = options["check"]
        dry_run: bool = options["dry_run"]

        loader = MigrationLoader()
        live_state = current_model_state()
        mig_state = loader.project_state_after()   # replay all known migrations

        any_changes = False

        for app_label in app_labels:
            # Skip apps that have no DynamoModels at all
            live_for_app = {k for k in live_state if k.startswith(f"{app_label}.")}
            mig_for_app = {k for k in mig_state if k.startswith(f"{app_label}.")}
            if not live_for_app and not mig_for_app:
                continue

            ops = detect_changes(mig_state, live_state, app_label)
            if not ops:
                if options["verbosity"] >= 2:
                    self.stdout.write(f"  {app_label}: No changes detected.")
                continue

            any_changes = True
            number = loader.next_number(app_label)
            migration_name = f"{number}_{name_suffix}"

            # Dependencies: depend on the current leaf migration(s) for this app
            leaves = loader.leaf_migrations(app_label)
            dependencies = [(app_label, leaf) for leaf in leaves]

            writer = MigrationWriter(
                app_label=app_label,
                migration_name=migration_name,
                operations=ops,
                dependencies=dependencies,
            )

            if dry_run:
                self.stdout.write(
                    self.style.MIGRATE_HEADING(
                        f"\n--- {app_label}/{migration_name}.py ---"
                    )
                )
                self.stdout.write(writer.as_string())
                continue

            # Locate the app directory and write the file
            app_config = django_apps.get_app_config(app_label)
            path = writer.write(app_config.path)

            self.stdout.write(
                self.style.SUCCESS(f"  Created dynamo migration: {path}")
            )
            for op in ops:
                self.stdout.write(f"    - {op.describe()}")

        if check_only and any_changes:
            raise SystemExit(1)

        if not any_changes:
            self.stdout.write("  No dynamo model changes detected.")
