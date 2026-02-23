"""
dynamo_backend.legacy
~~~~~~~~~~~~~~~~~~~~~
DEPRECATED: Legacy DynamoModel-based implementation.

This module is kept for backward compatibility only and will be removed in v1.0.0.
Please migrate to standard Django models. See README.md in this directory.
"""

from .models import DynamoModel
from .fields import (
    CharField,
    IntegerField,
    FloatField,
    BooleanField,
    DateTimeField,
    JSONField,
    UUIDField,
    ListField,
)
from .manager import DynamoManager
from .queryset import DynamoQuerySet

__all__ = [
    "DynamoModel",
    "CharField",
    "IntegerField",
    "FloatField",
    "BooleanField",
    "DateTimeField",
    "JSONField",
    "UUIDField",
    "ListField",
    "DynamoManager",
    "DynamoQuerySet",
]
