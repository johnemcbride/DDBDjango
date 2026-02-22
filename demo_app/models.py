"""
demo_app.models
~~~~~~~~~~~~~~~
A simple Blog domain: Author → Post → Comment

All models subclass DynamoModel — no relational DB required.
Foreign-key-style references are stored as plain string fields
(the referenced pk) following DynamoDB best practices.
"""

from dynamo_backend import (
    DynamoModel,
    CharField,
    IntegerField,
    BooleanField,
    DateTimeField,
    JSONField,
    UUIDField,
    ListField,
)
from dynamo_backend.fields import Field


class Author(DynamoModel):
    """A blog author."""

    class Meta:
        app_label = "demo_app"
        table_name = "demo_authors"

    username = CharField(max_length=60, nullable=False, index=True)
    email = CharField(max_length=254, default="")
    bio = CharField(max_length=500)
    created_at = DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.username


class Post(DynamoModel):
    """A blog post written by an Author."""

    class Meta:
        app_label = "demo_app"
        table_name = "demo_posts"

    title = CharField(max_length=200, nullable=False)
    slug = CharField(max_length=220, nullable=False, index=True)
    body = CharField(max_length=50_000)
    author_pk = CharField(max_length=36, index=True)   # FK → Author.pk
    published = BooleanField(default=False)
    public = BooleanField(default=True)
    tags = ListField(default=list)
    view_count = IntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    @property
    def author(self) -> Author:
        return Author.objects.get(pk=self.author_pk)

    def __str__(self) -> str:
        return self.title


class Comment(DynamoModel):
    """A comment on a Post."""

    class Meta:
        app_label = "demo_app"
        table_name = "demo_comments"

    post_pk = CharField(max_length=36, index=True)    # FK → Post.pk
    author_name = CharField(max_length=100, nullable=False)
    body = CharField(max_length=2_000, nullable=False)
    approved = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)

    @property
    def post(self) -> Post:
        return Post.objects.get(pk=self.post_pk)

    def __str__(self) -> str:
        return f"Comment by {self.author_name} on {self.post_pk}"
