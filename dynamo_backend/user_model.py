"""
dynamo_backend.user_model
~~~~~~~~~~~~~~~~~~~~~~~~~
DynamoUser — a standard Django AbstractBaseUser backed by DynamoDB.

Deliberately avoids the M2M Group/Permission machinery so the model can
live in a DynamoDB table with no join tables.

Permissions model: is_superuser=True → all permissions.
                   is_staff=True     → can access admin (limited by per-view checks).

Usage::

    # settings.py
    AUTH_USER_MODEL = 'dynamo_backend.DynamoUser'
"""
from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import models
from django.utils import timezone


class DynamoUserManager(BaseUserManager):
    """Manager with create_user / create_superuser helpers."""

    def _create_user(self, username, email, password, **extra_fields):
        if not username:
            raise ValueError("A username is required.")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username, email="", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email="", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"]:
            raise ValueError("Superuser must have is_staff=True.")
        if not extra_fields["is_superuser"]:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(username, email, password, **extra_fields)


class DynamoUser(AbstractBaseUser):
    """
    Full-featured user model stored in DynamoDB.

    Skips the M2M Group/Permission relations that AbstractUser adds;
    permissions are controlled entirely by the is_superuser / is_staff flags.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, db_index=True)
    email = models.EmailField(max_length=254, blank=True, default="")
    first_name = models.CharField(max_length=150, blank=True, default="")
    last_name = models.CharField(max_length=150, blank=True, default="")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    objects = DynamoUserManager()

    class Meta:
        app_label = "dynamo_backend"
        db_table = "dynamo_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    # ── name helpers ────────────────────────────────────────────────────
    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def get_short_name(self) -> str:
        return self.first_name or self.username

    def __str__(self) -> str:
        return self.username

    # ── permission helpers ───────────────────────────────────────────────
    # No M2M groups / permissions — superuser flag controls everything.

    @property
    def is_anonymous(self):
        return False

    @property
    def is_authenticated(self):
        return True

    def has_perm(self, perm, obj=None) -> bool:
        """Superusers have every permission; inactive users have none."""
        if not self.is_active:
            return False
        return self.is_superuser

    def has_perms(self, perm_list, obj=None) -> bool:
        return all(self.has_perm(p, obj) for p in perm_list)

    def has_module_perms(self, app_label) -> bool:
        """Staff and superusers can see all admin modules."""
        if not self.is_active:
            return False
        return self.is_superuser or self.is_staff

    # Stub attributes that Django admin / forms occasionally introspect
    @property
    def groups(self):
        """Return an empty queryset-compatible object (no groups)."""
        from django.contrib.auth.models import Group
        return Group.objects.none()

    @property
    def user_permissions(self):
        from django.contrib.auth.models import Permission
        return Permission.objects.none()
