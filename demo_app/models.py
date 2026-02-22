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

Relationship coverage
─────────────────────
FK (many-to-one)       : Post → Author, Comment → Post, PostRevision → Post
Nullable FK            : PostRevision.editor → Author (null=True, blank=True)
OneToOneField          : AuthorProfile ↔ Author
Self-referential FK    : Category.parent → Category
M2M (auto through)     : Post ↔ Tag  (via Post.labels)
M2M (explicit through) : Post ↔ Category via PostCategory (+ extra field)
"""
from __future__ import annotations

import uuid

from django.db import models


# ──────────────────────────────────────────────────────────────── Core models

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


class AuthorProfile(models.Model):
    """
    OneToOneField example — extends Author with social / contact info.

    Accessed as ``author.profile`` (reverse OneToOne accessor).
    Deleting an Author cascades to delete the profile.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.OneToOneField(
        Author,
        on_delete=models.CASCADE,
        related_name="profile",
        db_index=True,
    )
    website = models.URLField(blank=True, default="")
    twitter = models.CharField(max_length=50, blank=True, default="")
    location = models.CharField(max_length=100, blank=True, default="")
    avatar_url = models.URLField(blank=True, default="")
    follower_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return f"Profile({self.author_id})"


# ─────────────────────────────────────────── Tag (used in auto M2M with Post)

class Tag(models.Model):
    """
    Standalone tag model — linked to Post via an auto-created M2M join table
    (``demo_app_post_labels``).  No extra fields on the join.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True, db_index=True)
    slug = models.SlugField(max_length=60, unique=True, db_index=True)
    colour = models.CharField(max_length=20, blank=True, default="#cccccc")

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return self.name


# ───────────────── Category (self-referential FK + explicit M2M through table)

class Category(models.Model):
    """
    Self-referential FK example — a category can have a parent category,
    building an arbitrary-depth tree.

    Also used in the explicit M2M (Post ↔ Category via PostCategory).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, db_index=True)
    slug = models.SlugField(max_length=120, unique=True, db_index=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        db_index=True,
    )
    description = models.TextField(blank=True, default="")

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return self.name


# ─────────────────────────────────────────────────────────────── Post + Post-M2M

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
    tags = models.JSONField(default=list, blank=True)  # free-form JSON tag list
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── M2M: auto-created join table (Post ↔ Tag) ──────────────────────────
    labels = models.ManyToManyField(
        Tag,
        blank=True,
        related_name="posts",
        help_text="Structured tags (M2M, auto join table).",
    )

    # ── M2M: explicit through table (Post ↔ Category) ───────────────────────
    categories = models.ManyToManyField(
        Category,
        through="PostCategory",
        blank=True,
        related_name="posts",
        help_text="Categorisation (M2M with explicit through table).",
    )

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return self.title


class PostCategory(models.Model):
    """
    Explicit M2M through table — Post ↔ Category with an extra ``order``
    field that controls display order within a category.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="post_categories",
        db_index=True,
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="post_categories",
        db_index=True,
    )
    order = models.IntegerField(default=0)
    pinned = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "demo_app"

    def __str__(self) -> str:
        return f"{self.post_id} → {self.category_id} (order={self.order})"


# ─────────────────────────────────────────────────────────────── Comment

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


# ─────────────────────────────────────────────────────── PostRevision (nullable FK)

class PostRevision(models.Model):
    """
    Nullable FK example — ``editor`` is the Author who made the revision.
    May be NULL for system-generated or anonymous revisions.

    Also demonstrates a second FK on the same model (post + editor).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="revisions",
        db_index=True,
    )
    editor = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revisions",
        db_index=True,
    )
    body_snapshot = models.TextField(blank=True, default="")
    revision_number = models.IntegerField(default=1)
    change_summary = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "demo_app"
        ordering = ["revision_number"]

    def __str__(self) -> str:
        return f"Rev {self.revision_number} of {self.post_id}"
