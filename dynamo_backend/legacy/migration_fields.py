"""
dynamo_backend.migration_fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Serialise / deserialise Field instances to plain dicts so they can be
written into migration files and replayed to reconstruct model state.
"""

from __future__ import annotations

from typing import Any, Dict

from .fields import (
    Field, CharField, IntegerField, FloatField, BooleanField,
    DateTimeField, JSONField, UUIDField, ListField,
)

_FIELD_CLASSES: Dict[str, type] = {
    "CharField": CharField,
    "IntegerField": IntegerField,
    "FloatField": FloatField,
    "BooleanField": BooleanField,
    "DateTimeField": DateTimeField,
    "JSONField": JSONField,
    "UUIDField": UUIDField,
    "ListField": ListField,
}


def field_to_dict(field: Field) -> Dict[str, Any]:
    """Serialise a Field instance → plain dict (for state tracking & file writing)."""
    d: Dict[str, Any] = {
        "type": type(field).__name__,
        "primary_key": field.primary_key,
        "index": field.index,
        "nullable": field.nullable,
    }
    # Only store concrete (non-callable) defaults so the dict is JSON-safe
    if field._default is not None and not callable(field._default):
        d["default"] = field._default

    if isinstance(field, CharField):
        d["max_length"] = field.max_length
    if isinstance(field, DateTimeField):
        d["auto_now"] = field.auto_now
        d["auto_now_add"] = field.auto_now_add
    return d


def fields_equal(f1: Field, f2: Field) -> bool:
    """Return True if two field instances have the same serialised representation."""
    return field_to_dict(f1) == field_to_dict(f2)


def dict_to_field(d: Dict[str, Any]) -> Field:
    """Deserialise a plain dict → Field instance."""
    d = dict(d)
    field_type = d.pop("type")
    if field_type not in _FIELD_CLASSES:
        raise ValueError(f"Unknown field type: {field_type!r}")
    cls = _FIELD_CLASSES[field_type]
    # Reconstruct only the kwargs the field's __init__ accepts
    kwargs: Dict[str, Any] = {
        "primary_key": d.pop("primary_key", False),
        "index": d.pop("index", False),
        "nullable": d.pop("nullable", True),
    }
    if "default" in d:
        kwargs["default"] = d.pop("default")
    if cls is CharField and "max_length" in d:
        kwargs["max_length"] = d.pop("max_length")
    if cls is DateTimeField:
        kwargs["auto_now"] = d.pop("auto_now", False)
        kwargs["auto_now_add"] = d.pop("auto_now_add", False)
    return cls(**kwargs)


def field_repr(field: Field) -> str:
    """Return a Python source-code string that reconstructs this field, e.g.
    'CharField(max_length=200, nullable=False)'
    Used when writing migration files.
    """
    d = field_to_dict(field)
    d.pop("type")
    parts = []

    # CharField specifics
    if isinstance(field, CharField):
        parts.append(f"max_length={d.pop('max_length')}")
    if isinstance(field, DateTimeField):
        if d.get("auto_now"):
            parts.append("auto_now=True")
        if d.get("auto_now_add"):
            parts.append("auto_now_add=True")
        d.pop("auto_now", None)
        d.pop("auto_now_add", None)

    if d.get("primary_key"):
        parts.append("primary_key=True")
    d.pop("primary_key")
    if not d.get("nullable", True):
        parts.append("nullable=False")
    d.pop("nullable")
    if d.get("index"):
        parts.append("index=True")
    d.pop("index")
    if "default" in d:
        val = d["default"]
        parts.append(f"default={val!r}")

    cls_name = type(field).__name__
    return f"{cls_name}({', '.join(parts)})"
