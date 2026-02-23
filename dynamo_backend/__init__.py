"""
dynamo_backend — a transparent DynamoDB backend for Django.

This package provides a Django database backend that stores data in DynamoDB
instead of a relational database. Use standard Django models — the backend
handles DynamoDB persistence automatically.

Usage::

    # settings.py
    DATABASES = {
        "default": {
            "ENGINE": "dynamo_backend.backends.dynamodb",
            "NAME": "default",
            "REGION": "us-east-1",
            # ... other connection settings
        }
    }
    
    DATABASE_ROUTERS = ["dynamo_backend.router.DynamoRouter"]
    
    # models.py
    from django.db import models
    
    class Post(models.Model):
        title = models.CharField(max_length=200)
        content = models.TextField()
        published = models.BooleanField(default=False)

Legacy API (deprecated):
  For backward compatibility, the old DynamoModel-based API is available in
  dynamo_backend.legacy. This will be removed in a future major version.
"""

__version__ = "0.1.0"

from .exceptions import (
    DynamoObjectNotFound,
    DynamoMultipleObjectsReturned,
    DynamoValidationError,
    DynamoTableError,
)

# Legacy imports for backward compatibility (DEPRECATED)
# These will be removed in v1.0.0
def __getattr__(name):
    """Lazy import legacy classes with deprecation warning."""
    legacy_classes = {
        "DynamoModel": "legacy.models",
        "CharField": "legacy.fields",
        "IntegerField": "legacy.fields",
        "FloatField": "legacy.fields",
        "BooleanField": "legacy.fields",
        "DateTimeField": "legacy.fields",
        "JSONField": "legacy.fields",
        "UUIDField": "legacy.fields",
        "ListField": "legacy.fields",
        "DynamoManager": "legacy.manager",
        "DynamoQuerySet": "legacy.queryset",
    }
    
    if name in legacy_classes:
        import warnings
        warnings.warn(
            f"{name} is deprecated. Use standard Django models instead. "
            f"See dynamo_backend.legacy.README.md for migration guide.",
            DeprecationWarning,
            stacklevel=2,
        )
        module_path = legacy_classes[name]
        from importlib import import_module
        module = import_module(f".{module_path}", package="dynamo_backend")
        return getattr(module, name)
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DynamoObjectNotFound",
    "DynamoMultipleObjectsReturned",
    "DynamoValidationError",
    "DynamoTableError",
]
