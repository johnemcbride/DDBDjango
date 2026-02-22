"""
dynamo_backend.m2m
~~~~~~~~~~~~~~~~~~
_DynamoManyToManyDescriptor — replaces the standard ManyToManyDescriptor so
M2M reads do a two-step DynamoDB query instead of a SQL JOIN:

  Step 1: Query through table via source-field GSI  -> list of target PKs
  Step 2: filter(pk__in=target_ids)                 -> BatchGetItem target model
"""
from __future__ import annotations

from functools import cached_property

from django.db.models.fields.related_descriptors import (
    ManyToManyDescriptor,
    create_forward_many_to_many_manager,
)


def _create_dynamo_m2m_manager(superclass, rel, reverse):
    BaseCls = create_forward_many_to_many_manager(superclass, rel, reverse)

    class DynamoManyRelatedManager(BaseCls):
        def _apply_rel_filters(self, queryset):
            queryset._add_hints(instance=self.instance)
            if self._db:
                queryset = queryset.using(self._db)

            source_pk = self.related_val[0]
            target_ids = list(
                self.through._default_manager
                .filter(**{f"{self.source_field_name}_id": source_pk})
                .values_list(f"{self.target_field_name}_id", flat=True)
            )

            if not target_ids:
                return queryset.none()

            return queryset.filter(pk__in=target_ids)

    DynamoManyRelatedManager.__name__ = "DynamoManyRelatedManager"
    return DynamoManyRelatedManager


class _DynamoManyToManyDescriptor(ManyToManyDescriptor):
    """Descriptor that uses the two-step DynamoDB M2M read path."""

    @cached_property
    def related_manager_cls(self):
        related_model = self.rel.related_model if self.reverse else self.rel.model
        return _create_dynamo_m2m_manager(
            related_model._default_manager.__class__,
            self.rel,
            reverse=self.reverse,
        )
