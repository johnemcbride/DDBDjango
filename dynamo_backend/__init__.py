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
"""

__version__ = "0.1.0"

from .exceptions import (
    DynamoObjectNotFound,
    DynamoMultipleObjectsReturned,
    DynamoValidationError,
    DynamoTableError,
)



__all__ = [
    "DynamoObjectNotFound",
    "DynamoMultipleObjectsReturned",
    "DynamoValidationError",
    "DynamoTableError",
]
