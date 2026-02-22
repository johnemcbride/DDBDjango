"""
demo_app.admin
~~~~~~~~~~~~~~
Standard Django ModelAdmin registrations for the DynamoDB-backed models.

ForeignKey fields (author, post) are displayed as linked objects in the
change list and change form — exactly the same as a relational Django project.
No custom DynamoModelAdmin needed.
"""
from django.contrib import admin

from .models import Author, Post, Comment


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "email", "created_at")
    search_fields = ("username", "email")
    readonly_fields = ("id", "created_at")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    # 'author' shows the Author.__str__ (username) in the list, not a raw UUID.
    list_display = ("id", "title", "author", "slug", "published", "public", "view_count", "created_at")
    list_filter = ("published", "public")
    search_fields = ("title", "slug")
    raw_id_fields = ("author",)
    readonly_fields = ("id", "created_at", "updated_at")
    # Disable the "X total results" COUNT(*) scan — with millions of DynamoDB
    # rows a full-table count scan is prohibitively slow / fails on LocalStack.
    show_full_result_count = False
    list_per_page = 50


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    # 'post' shows Post.__str__ (title), not a raw UUID.
    list_display = ("id", "author_name", "post", "approved", "created_at")
    list_filter = ("approved",)
    search_fields = ("author_name", "body")
    raw_id_fields = ("post",)
    readonly_fields = ("id", "created_at")
