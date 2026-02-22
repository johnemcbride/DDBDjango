"""
demo_app.admin
~~~~~~~~~~~~~~
Standard Django ModelAdmin registrations for the DynamoDB-backed models.

ForeignKey fields (author, post) are displayed as linked objects in the
change list and change form — exactly the same as a relational Django project.
No custom DynamoModelAdmin needed.

Covers every relation type in demo_app.models:
  • FK (many-to-one):          Post → Author, Comment → Post
  • Nullable FK:               PostRevision.editor → Author
  • OneToOneField:             AuthorProfile ↔ Author
  • Self-referential FK:       Category.parent → Category
  • M2M (auto through):        Post ↔ Tag  (inline)
  • M2M (explicit through):    Post ↔ Category via PostCategory
"""
from django.contrib import admin

from dynamo_backend.admin_search import OpenSearchAdminMixin
from .models import (
    Author, AuthorProfile,
    Tag,
    Category,
    Post, PostCategory,
    Comment,
    PostRevision,
)


# ─────────────────────────────────────────────────────────── Author + Profile

class AuthorProfileInline(admin.StackedInline):
    model = AuthorProfile
    extra = 0
    readonly_fields = ("id", "updated_at")
    fields = ("id", "website", "twitter", "location", "avatar_url", "follower_count", "updated_at")


@admin.register(Author)
class AuthorAdmin(OpenSearchAdminMixin, admin.ModelAdmin):
    list_display = ("id", "username", "email", "created_at")
    search_fields = ("username", "email")
    readonly_fields = ("id", "created_at")
    inlines = [AuthorProfileInline]


@admin.register(AuthorProfile)
class AuthorProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "website", "twitter", "location", "follower_count")
    search_fields = ("twitter", "location")
    readonly_fields = ("id", "updated_at")
    raw_id_fields = ("author",)


# ─────────────────────────────────────────────────────────── Tag

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "colour")
    search_fields = ("name", "slug")
    readonly_fields = ("id",)


# ─────────────────────────────────────────────────────────── Category (self-ref FK)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "parent")
    search_fields = ("name", "slug")
    readonly_fields = ("id",)
    raw_id_fields = ("parent",)


# ─────────────────────────────────────────────────────────── Post + M2M inlines

class PostCategoryInline(admin.TabularInline):
    """Explicit M2M through table inline — shows order + pinned."""
    model = PostCategory
    extra = 0
    readonly_fields = ("id", "added_at")
    fields = ("id", "category", "order", "pinned", "added_at")
    raw_id_fields = ("category",)


@admin.register(Post)
class PostAdmin(OpenSearchAdminMixin, admin.ModelAdmin):
    # 'author' shows the Author.__str__ (username) in the list, not a raw UUID.
    list_display = ("id", "title", "author", "slug", "published", "public", "view_count", "created_at")
    list_filter = ("published", "public")
    search_fields = ("title", "slug")
    readonly_fields = ("id", "created_at", "updated_at")
    # Disable the "X total results" COUNT(*) scan — with millions of DynamoDB
    # rows a full-table count scan is prohibitively slow / fails on LocalStack.
    show_full_result_count = False
    list_per_page = 50
    # M2M (auto join table) edited via filter_horizontal widget
    filter_horizontal = ("labels",)
    inlines = [PostCategoryInline]


@admin.register(PostCategory)
class PostCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "category", "order", "pinned", "added_at")
    list_filter = ("pinned",)
    readonly_fields = ("id", "added_at")
    raw_id_fields = ("post", "category")


# ─────────────────────────────────────────────────────────── Comment

@admin.register(Comment)
class CommentAdmin(OpenSearchAdminMixin, admin.ModelAdmin):
    # 'post' shows Post.__str__ (title), not a raw UUID.
    list_display = ("id", "author_name", "post", "approved", "created_at")
    list_filter = ("approved",)
    search_fields = ("author_name", "body")
    raw_id_fields = ("post",)
    readonly_fields = ("id", "created_at")


# ─────────────────────────────────────────────────────────── PostRevision (nullable FK)

@admin.register(PostRevision)
class PostRevisionAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "editor", "revision_number", "change_summary", "created_at")
    search_fields = ("change_summary",)
    readonly_fields = ("id", "created_at")
    raw_id_fields = ("post", "editor")
