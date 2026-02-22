"""
dynamo_backend — an opinionated DynamoDB backend for Django.

Provides:
  - DynamoModel: base model class (replaces django.db.models.Model)
  - Fields: CharField, IntegerField, BooleanField, DateTimeField, JSONField, etc.
  - DynamoManager / DynamoQuerySet: filter/get/all/create/delete API
  - Table management helpers
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
from .exceptions import (
    DynamoObjectNotFound,
    DynamoMultipleObjectsReturned,
    DynamoValidationError,
    DynamoTableError,
)

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
    "DynamoObjectNotFound",
    "DynamoMultipleObjectsReturned",
    "DynamoValidationError",
    "DynamoTableError",
]
