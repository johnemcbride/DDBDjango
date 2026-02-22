"""
dynamo_backend.models
~~~~~~~~~~~~~~~~~~~~~
DynamoModel — the base class for all DynamoDB-backed models.

Usage::

    from dynamo_backend import DynamoModel, CharField, DateTimeField, UUIDField

    class Post(DynamoModel):
        class Meta:
            table_name = "posts"

        title = CharField(max_length=200, nullable=False)
        body  = CharField(max_length=10_000)
        created_at = DateTimeField(auto_now_add=True)

    # CRUD
    post = Post.objects.create(title="Hello", body="World")
    post.title = "Updated"
    post.save()
    Post.objects.get(pk=post.pk)
    post.delete()
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type

from .exceptions import DynamoObjectNotFound, DynamoValidationError, DynamoMultipleObjectsReturned
from .fields import Field, UUIDField, DateTimeField
from .manager import DynamoManager
from .connection import get_resource, table_name as prefixed


# Global registry of all concrete DynamoModel subclasses.
_dynamo_model_registry: list = []


class _FieldsDict(dict):
    """
    A dict subclass where *iteration* yields Field values (not string keys).
    Django admin does ``for field in opts.fields`` expecting Field objects;
    our own code uses ``opts.fields[name]``, ``name in opts.fields``, and
    ``opts.fields.items()`` — all those remain dict-style.
    """

    def __iter__(self):
        return iter(self.values())

    # Keep string-key membership test intact (used by our own code)
    def __contains__(self, item):
        if isinstance(item, str):
            return dict.__contains__(self, item)
        return any(v is item for v in self.values())


class _AdminPkField:
    """Minimal Django pk-field interface used by django.contrib.admin internals."""
    attname = "pk"
    name = "pk"
    verbose_name = "pk"
    column = None
    remote_field = None
    related_model = None
    one_to_one = False
    many_to_one = False
    many_to_many = False
    one_to_many = False
    is_relation = False
    auto_created = False
    unique = True
    null = False
    concrete = True
    editable = True
    hidden = False
    model = None
    # Django admin display/form compat
    empty_values = list((None, "", [], (), {}))
    flatchoices: list = []
    choices: list = []
    help_text: str = ""
    encoder = None
    decimal_places = None

    def related_query_name(self) -> str:
        return ""

    def value_to_string(self, obj):
        return str(obj.pk)

    def value_from_object(self, obj):
        return obj.pk


class Options:
    """Mirrors Django's _meta; holds field registry and table name."""

    def __init__(self, meta, app_label: str, model_name: str, class_name: str = ""):
        self.fields: _FieldsDict = _FieldsDict()
        self.app_label = app_label
        self.model_name = model_name
        self.table_name: str = getattr(meta, "table_name", None) or f"{app_label}_{model_name}"
        self.abstract: bool = getattr(meta, "abstract", False)

        # Attributes expected by django.contrib.admin
        self.object_name = class_name or model_name.capitalize()
        self.verbose_name = model_name.lower()
        self.verbose_name_plural = model_name.lower() + "s"
        self.ordering: list = []
        self.pk = _AdminPkField()
        self.swapped = False
        self.managed = True
        # ORM-style constraint/relation stubs (DynamoDB has none of these)
        self.unique_together: list = []
        self.total_unique_constraints: list = []
        self.many_to_many: list = []
        self.auto_created = False
        self.parents: dict = {}
        self.all_parents: list = []
        self.related_fkey_lookups: list = []
        # Django 6.0+ attributes
        self.is_composite_pk = False
        self.auto_field = None

    def get_field(self, field_name: str) -> Field:
        from django.core.exceptions import FieldDoesNotExist
        if field_name == "pk":
            return self.pk  # type: ignore[return-value]
        if field_name in self.fields:
            return self.fields[field_name]
        raise FieldDoesNotExist(f"No field named {field_name!r} on {self.model_name}")

    def get_fields(self, include_parents=True, include_hidden=False):
        return list(self.fields.values())

    @property
    def concrete_fields(self):
        """All concrete (non-deferred) fields — used by get_deferred_fields."""
        return list(self.fields.values())

    @property
    def private_fields(self):
        return []

    @property
    def related_objects(self):
        return []

    @property
    def app_config(self):
        from django.apps import apps as django_apps
        try:
            return django_apps.get_app_config(self.app_label)
        except LookupError:
            return None


class DynamoModelMetaclass(type):
    def __new__(mcs, name, bases, namespace):
        # Pass-through for the base DynamoModel class itself
        if name == "DynamoModel" and not any(
            hasattr(b, "_meta") for b in bases
        ):
            return super().__new__(mcs, name, bases, namespace)

        # Collect inner Meta
        meta_cls = namespace.get("Meta", type("Meta", (), {}))
        app_label = getattr(meta_cls, "app_label", "app")
        model_name = name.lower()

        cls = super().__new__(mcs, name, bases, namespace)
        cls._meta = Options(meta_cls, app_label, model_name, class_name=name)
        cls._meta.model = cls  # required by Django admin's get_deleted_objects & router

        # Inherit fields from base classes
        for base in reversed(bases):
            if hasattr(base, "_meta"):
                for fname, field in base._meta.fields.items():
                    cls._meta.fields.setdefault(fname, copy.deepcopy(field))

        # Register fields declared on this class
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, Field):
                attr_value.contribute_to_class(cls, attr_name)

        # Ensure every model has a `pk` field
        if "pk" not in cls._meta.fields:
            pk_field = UUIDField(primary_key=True, nullable=False)
            pk_field.contribute_to_class(cls, "pk")

        # Attach default manager
        manager = DynamoManager()
        manager.contribute_to_class(cls, "objects")
        cls._default_manager = manager

        # Exception shortcuts (Django-style)
        cls.DoesNotExist = type("DoesNotExist", (DynamoObjectNotFound,), {"__module__": cls.__module__})
        cls.MultipleObjectsReturned = type("MultipleObjectsReturned", (DynamoMultipleObjectsReturned,), {"__module__": cls.__module__})

        # Register concrete models
        if not cls._meta.abstract:
            _dynamo_model_registry.append(cls)

        return cls


class DynamoModel(metaclass=DynamoModelMetaclass):
    """Base class for all DynamoDB-backed models."""

    def __init__(self, **kwargs):
        # Set field defaults then apply kwargs
        for name, field in self._meta.fields.items():
            setattr(self, name, field.get_default())
        for key, value in kwargs.items():
            setattr(self, key, value)

    # ---------------------------------------------------------------- CRUD

    @classmethod
    def _create(cls, **kwargs) -> "DynamoModel":
        obj = cls(**kwargs)
        obj._pre_save()
        obj._validate()
        table = get_resource().Table(prefixed(cls._meta.table_name))
        table.put_item(Item=obj._to_dynamo_item())
        return obj

    def save(self) -> None:
        self._pre_save()
        self._validate()
        table = get_resource().Table(prefixed(self._meta.table_name))
        table.put_item(Item=self._to_dynamo_item())

    def delete(self) -> None:
        table = get_resource().Table(prefixed(self._meta.table_name))
        table.delete_item(Key={"pk": str(self.pk)})

    def refresh_from_db(self) -> None:
        table = get_resource().Table(prefixed(self._meta.table_name))
        response = table.get_item(Key={"pk": str(self.pk)})
        item = response.get("Item")
        if not item:
            raise self.DoesNotExist(f"{self.__class__.__name__} with pk={self.pk} was deleted.")
        fresh = self._from_dynamo_item(item)
        for name in self._meta.fields.keys():
            setattr(self, name, getattr(fresh, name))

    # --------------------------------------------------------- serialisation

    def _pre_save(self) -> None:
        """Apply auto_now / ensure pk."""
        for name, field in self._meta.fields.items():
            if isinstance(field, DateTimeField) and field.auto_now:
                setattr(self, name, datetime.now(tz=timezone.utc))
            current = getattr(self, name, None)
            if current is None:
                default = field.get_default()
                if default is not None:
                    setattr(self, name, default)

    def _validate(self) -> None:
        for name, field in self._meta.fields.items():
            value = getattr(self, name, None)
            field.validate(value)

    def _to_dynamo_item(self) -> Dict:
        item: Dict[str, Any] = {}
        for name, field in self._meta.fields.items():
            value = getattr(self, name, None)
            serialised = field.to_dynamo(value)
            if serialised is not None:
                item[name] = serialised
        return item

    @classmethod
    def _from_dynamo_item(cls, item: Dict) -> "DynamoModel":
        kwargs: Dict[str, Any] = {}
        for name, field in cls._meta.fields.items():
            if name in item:
                kwargs[name] = field.from_dynamo(item[name])
            else:
                # Attribute absent from old item — fall back to field default
                kwargs[name] = field.get_default()
        return cls(**kwargs)

    # ---------------------------------------------------------------- repr

    def to_dict(self) -> Dict:
        return {name: getattr(self, name, None) for name in self._meta.fields.keys()}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} pk={getattr(self, 'pk', '?')!r}>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return str(self.pk) == str(other.pk)

    def __hash__(self):
        return hash(self.pk)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} ({getattr(self, 'pk', '?')})"

    # ------------------------------------------------ Django admin / ORM compat

    def serializable_value(self, field_name: str):
        """Return the field value suitable for serialisation.
        Mirrors django.db.models.Model.serializable_value.
        """
        from django.core.exceptions import FieldDoesNotExist
        try:
            field = self._meta.get_field(field_name)
        except FieldDoesNotExist:
            return getattr(self, field_name, None)
        return getattr(self, field.attname, None)

    def get_deferred_fields(self) -> set:
        """DynamoDB models never defer fields — always return empty set."""
        return set()

    def validate_unique(self, exclude=None):
        """No-op: uniqueness is handled at the DynamoDB level."""
        pass

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        """No-op: DynamoDB has no SQL-level constraints to validate."""
        pass

    class _State:
        db = "default"
        adding = False

    _state = _State()
