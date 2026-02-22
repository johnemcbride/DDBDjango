"""
dynamo_backend.user_model
~~~~~~~~~~~~~~~~~~~~~~~~~
DynamoUser — a standard Django AbstractUser backed by DynamoDB.

Groups and user_permissions are stored as DynamoDB through-tables via
DynamoManyToManyField (two-step read: GSI query → BatchGetItem).

Usage::

    # settings.py
    AUTH_USER_MODEL = 'dynamo_backend.DynamoUser'
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from dynamo_backend.m2m import DynamoManyToManyField


class DynamoUser(AbstractUser):
    """
    Full-featured user model stored in DynamoDB.

    Inherits all of Django's AbstractUser fields (username, email,
    first/last name, is_staff, is_superuser, date_joined, etc.) and
    replaces the two ManyToManyField relations with DynamoDB-aware ones.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    groups = DynamoManyToManyField(
        "auth.Group",
        verbose_name="groups",
        blank=True,
        help_text=(
            "The groups this user belongs to. A user will get all permissions "
            "granted to each of their groups."
        ),
        related_name="user_set",
        related_query_name="user",
    )
    user_permissions = DynamoManyToManyField(
        "auth.Permission",
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="user_set",
        related_query_name="user",
    )

    class Meta:
        app_label = "dynamo_backend"
        db_table = "dynamo_user"
        verbose_name = "user"
        verbose_name_plural = "users"
