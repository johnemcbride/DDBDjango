"""
dynamo_backend.manager
~~~~~~~~~~~~~~~~~~~~~~
DynamoManager is the entry-point for all table-level operations.
It is automatically attached to every DynamoModel as `objects`.
"""

from __future__ import annotations

from typing import Any, Dict

from .queryset import DynamoQuerySet
from .connection import get_resource, table_name as prefixed


class DynamoManager:
    """Descriptor-style manager. Accessed as ``MyModel.objects``."""

    def __init__(self):
        self._model = None

    def contribute_to_class(self, cls, name: str) -> None:
        self._model = cls
        setattr(cls, name, ManagerDescriptor(self))

    # --------------------------------------------------- queryset shortcuts

    def get_queryset(self) -> DynamoQuerySet:
        return DynamoQuerySet(self._model)

    def all(self) -> DynamoQuerySet:
        return self.get_queryset().all()

    def filter(self, **kwargs) -> DynamoQuerySet:
        return self.get_queryset().filter(**kwargs)

    def exclude(self, **kwargs) -> DynamoQuerySet:
        return self.get_queryset().exclude(**kwargs)

    def get(self, **kwargs) -> Any:
        return self.get_queryset().get(**kwargs)

    def order_by(self, field: str) -> "DynamoQuerySet":
        return self.get_queryset().order_by(field)

    def first(self):
        return self.get_queryset().first()

    def count(self) -> int:
        return self.get_queryset().count()

    def values(self, *fields):
        return self.get_queryset().values(*fields)

    # --------------------------------------------------- write operations

    def create(self, **kwargs) -> Any:
        return self._model._create(**kwargs)

    def get_or_create(self, defaults: Dict = None, **kwargs):
        try:
            obj = self.get(**kwargs)
            return obj, False
        except self._model.DoesNotExist:
            params = {**kwargs, **(defaults or {})}
            obj = self.create(**params)
            return obj, True

    def bulk_create(self, objects) -> None:
        """Write a list of unsaved DynamoModel instances in one batch."""
        table = get_resource().Table(prefixed(self._model._meta.table_name))
        with table.batch_writer() as batch:
            for obj in objects:
                obj._pre_save()
                batch.put_item(Item=obj._to_dynamo_item())

    def delete(self) -> int:
        return self.get_queryset().delete()


class ManagerDescriptor:
    """Prevents accessing  `objects`  via an instance."""

    def __init__(self, manager: DynamoManager):
        self._manager = manager

    def __get__(self, obj, cls=None):
        if obj is not None:
            raise AttributeError("Manager is not accessible via model instances.")
        # Return a fresh manager bound to the class
        mgr = DynamoManager()
        mgr._model = cls
        return mgr
