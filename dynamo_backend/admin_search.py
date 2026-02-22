"""
dynamo_backend.admin_search
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Drop-in Django admin mixin that routes search queries through OpenSearch
(backed by LocalStack) rather than performing a full DynamoDB table scan.

Usage
─────
    from dynamo_backend.admin_search import OpenSearchAdminMixin

    @admin.register(Post)
    class PostAdmin(OpenSearchAdminMixin, admin.ModelAdmin):
        search_fields = ("title", "slug")
        ...

When OpenSearch is available the mixin's ``get_search_results()`` override
calls ``opensearch_sync.search_pks()`` and filters the queryset to the
returned PKs only.  If OpenSearch is unavailable (not yet reachable, domain
still cold, etc.) it transparently delegates to the default implementation,
which falls back to the DynamoDB scan-based search.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("dynamo_backend.admin_search")


class OpenSearchAdminMixin:
    """Mixin for ModelAdmin subclasses that adds OpenSearch-backed search."""

    def get_search_results(self, request, queryset, search_term):
        """Override: delegate to OpenSearch when available, DDB scan otherwise."""
        if not search_term:
            return queryset, False

        try:
            from dynamo_backend import opensearch_sync

            # Resolve the physical DynamoDB table name (respects table_prefix)
            try:
                from django.db import connections
                db_alias = queryset.db or "default"
                conn = connections[db_alias]
                prefix = conn.settings_dict.get("OPTIONS", {}).get("table_prefix", "")
            except Exception:
                prefix = ""

            table_name = prefix + queryset.model._meta.db_table
            fields = list(self.search_fields or [])

            pks = opensearch_sync.search_pks(table_name, search_term, fields)

            if pks is None:
                # OpenSearch unavailable — fall back to DDB scan
                logger.debug(
                    "OpenSearch unavailable for %s, falling back to DDB scan",
                    table_name,
                )
                return super().get_search_results(request, queryset, search_term)

            # pks is a list of strings; cast to the PK type expected by the model
            pk_field = queryset.model._meta.pk
            import uuid as _uuid
            import django.db.models.fields as _F
            cast_pks = []
            for pk in pks:
                try:
                    if isinstance(pk_field, _F.UUIDField):
                        cast_pks.append(_uuid.UUID(pk))
                    elif isinstance(pk_field, (_F.IntegerField, _F.BigIntegerField,
                                               _F.AutoField, _F.BigAutoField,
                                               _F.SmallAutoField)):
                        cast_pks.append(int(pk))
                    else:
                        cast_pks.append(pk)
                except (ValueError, AttributeError):
                    cast_pks.append(pk)

            return queryset.filter(pk__in=cast_pks), False

        except Exception as exc:
            logger.warning(
                "OpenSearchAdminMixin.get_search_results failed: %s — falling back",
                exc,
            )
            return super().get_search_results(request, queryset, search_term)
