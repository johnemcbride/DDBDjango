"""
dynamo_backend.m2m
~~~~~~~~~~~~~~~~~~
DynamoManyToManyField — two-step DynamoDB M2M (no SQL JOIN).

Step 1: Query through table via source-field GSI  -> list of target PKs
Step 2: BatchGetItem the target model via pk__in
"""
from __future__ import annotations

from functools import cached_property

from django.db.models import ManyToManyField
from django.db.models.fields.related_descriptors import (
    ManyToManyDescriptor,
    create_forward_many_to_many_manager,
)


# ─────────────────────────────────────────────── two-step manager factory


def _create_dynamo_m2m_manager(superclass, rel, reverse):
    """
    Wraps Django's M2M manager factory, replacing _apply_rel_filters with
    a DynamoDB-friendly two-step query.
    """
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


# ─────────────────────────────────────────────── descriptor override


class _DynamoManyToManyDescriptor(ManyToManyDescriptor):
    """
    Injects _create_dynamo_m2m_manager in place of
    create_forward_many_to_many_manager.
    """

    @cached_property
    def related_manager_cls(self):
        related_model = self.rel.related_model if self.reverse else self.rel.model
        return _create_dynamo_m2m_manager(
            related_model._default_manager.__class__,
            self.rel,
            reverse=self.reverse,
        )


# ─────────────────────────────────────────────── field


class DynamoManyToManyField(ManyToManyField):
    """
    Drop-in replacement for ManyToManyField that uses the DynamoDB
    two-step manager for all read access.
    """

    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        setattr(
            cls, name,
            _DynamoManyToManyDescriptor(self.remote_field, reverse=False),
        )

    def contribute_to_related_class(self, cls, related):
        super().contribute_to_related_class(cls, related)
        accessor_name = related.get_accessor_name()
        if accessor_name and hasattr(cls, accessor_name):
            setattr(
                cls, accessor_name,
                _DynamoManyToManyDescriptor(self.remote_field, reverse=True),
            )
