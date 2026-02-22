"""
demo_app.models
~~~~~~~~~~~~~~~
Standard Django models backed by DynamoDB.

All models use django.db.models.Model and standard field types.
The DynamoDB backend handles persistence transparently via the database router.

Design notes
────────────
• Primary keys are UUIDs stored as strings in DynamoDB.
• ForeignKey relationships work normally — Django resolves them via separate
  GetItem calls.  The admin shows linked objects by their __str__, not raw PKs.
• auto_now_add / auto_now work exactly as in a relational Django project.
• JSONField (tags) is stored natively as a DynamoDB List/Map attribute.
"""
from __future__ import annotations

import uuid

from django.db import models


class Author(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=60, unique=True, db_index=True)
    email = models.EmailField(max_length=254, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return self.username


class Post(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name="posts",
        db_index=True,
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, db_index=True)
    body = models.TextField(blank=True, default="")
    published = models.BooleanField(default=False)
    public = models.BooleanField(default=True)
    tags = models.JSONField(default=list, blank=True)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return self.title


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="comments",
        db_index=True,
    )
    author_name = models.CharField(max_length=100, blank=True, default="")
    body = models.TextField(blank=True, default="")
    approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return f"Comment by {self.author_name}"
