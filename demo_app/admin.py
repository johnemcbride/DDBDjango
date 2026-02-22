from django.contrib import admin

from dynamo_backend.admin import DynamoModelAdmin
from .models import Author, Post, Comment


@admin.register(Author)
class AuthorAdmin(DynamoModelAdmin):
    list_display = ("pk", "username", "email", "created_at")
    search_fields = ("username", "email")


@admin.register(Post)
class PostAdmin(DynamoModelAdmin):
    list_display = ("pk", "title", "slug", "published", "public", "view_count", "created_at")
    search_fields = ("title", "slug")
    list_filter = ()


@admin.register(Comment)
class CommentAdmin(DynamoModelAdmin):
    list_display = ("pk", "author_name", "post_pk", "approved", "created_at")
    search_fields = ("author_name", "body")
