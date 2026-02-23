"""
demo_app.views
~~~~~~~~~~~~~~
Simple JSON REST views for the Blog demo.
No DRF required — uses plain Django JsonResponse.

Endpoints (original):
    GET  /api/authors/                  list authors
    POST /api/authors/                  create author
    GET  /api/authors/<pk>/             retrieve author
    PUT  /api/authors/<pk>/             update author
    DELETE /api/authors/<pk>/           delete author
    GET  /api/authors/<pk>/posts/       paginated posts for author
    GET  /api/authors/<pk>/profile/     get author profile
    POST /api/authors/<pk>/profile/     create or update author profile

    GET  /api/posts/                    list posts (optionally ?author_id=)
    POST /api/posts/                    create post
    GET  /api/posts/<pk>/               retrieve post + comments
    PUT  /api/posts/<pk>/               update post
    DELETE /api/posts/<pk>/             delete post
    GET  /api/posts/<pk>/revisions/     list revisions
    POST /api/posts/<pk>/revisions/     create revision
    GET  /api/posts/<pk>/labels/        list tags on post
    POST /api/posts/<pk>/labels/        add tag to post
    DELETE /api/posts/<pk>/labels/<tag_pk>/  remove tag from post
    GET  /api/posts/<pk>/categories/    list categories on post
    POST /api/posts/<pk>/categories/    add category to post (PostCategory)
    DELETE /api/postcategories/<pk>/    remove PostCategory entry

    POST /api/posts/<pk>/comments/      add comment
    DELETE /api/comments/<pk>/          delete comment

    GET  /api/tags/                     list tags
    POST /api/tags/                     create tag
    DELETE /api/tags/<pk>/              delete tag

    GET  /api/categories/               list categories
    POST /api/categories/               create category
    DELETE /api/categories/<pk>/        delete category
"""

import json
import time
import uuid
import base64

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Author, Post, Comment, Tag, Category, AuthorProfile, PostRevision, PostCategory


def _body(request) -> dict:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return {}


def _str_pk(value) -> str | None:
    """Normalize a pk (UUID or str) to string for JSON output."""
    if value is None:
        return None
    return str(value)


def _author_dict(a: Author) -> dict:
    return {
        "pk": _str_pk(a.pk),
        "username": a.username,
        "email": a.email,
        "bio": a.bio,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _post_dict(p: Post) -> dict:
    return {
        "pk": _str_pk(p.pk),
        "title": p.title,
        "slug": p.slug,
        "body": p.body,
        # Expose author_id (UUID string) for backward compat + convenience
        "author_id": _str_pk(p.author_id),
        "published": p.published,
        "public": p.public,
        "tags": p.tags or [],
        "view_count": p.view_count,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _comment_dict(c: Comment) -> dict:
    return {
        "pk": _str_pk(c.pk),
        "post_id": _str_pk(c.post_id),
        "author_name": c.author_name,
        "body": c.body,
        "approved": c.approved,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ─────────────────────────────────────────────────────── Author views

@method_decorator(csrf_exempt, name="dispatch")
class AuthorListView(View):
    def get(self, request):
        authors = [_author_dict(a) for a in Author.objects.all()]
        return JsonResponse({"authors": authors})

    def post(self, request):
        data = _body(request)
        try:
            author = Author.objects.create(
                username=data["username"],
                email=data.get("email", ""),
                bio=data.get("bio", ""),
            )
        except (KeyError, Exception) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_author_dict(author), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class AuthorDetailView(View):
    def _get_or_404(self, pk):
        try:
            return Author.objects.get(pk=pk)
        except (Author.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        author = self._get_or_404(pk)
        if not author:
            return JsonResponse({"error": "Not found"}, status=404)
        return JsonResponse(_author_dict(author))

    def put(self, request, pk):
        author = self._get_or_404(pk)
        if not author:
            return JsonResponse({"error": "Not found"}, status=404)
        data = _body(request)
        for field in ("username", "email", "bio"):
            if field in data:
                setattr(author, field, data[field])
        author.save()
        return JsonResponse(_author_dict(author))

    def delete(self, request, pk):
        author = self._get_or_404(pk)
        if not author:
            return JsonResponse({"error": "Not found"}, status=404)
        author.delete()
        return JsonResponse({}, status=204)


# ─────────────────────────────────────────────────────── Post views

@method_decorator(csrf_exempt, name="dispatch")
class PostListView(View):
    def get(self, request):
        # Support both legacy ?author_pk= and new ?author_id= query params
        author_id = request.GET.get("author_id") or request.GET.get("author_pk")
        if author_id:
            posts = Post.objects.filter(author_id=author_id)
        else:
            posts = Post.objects.all()
        return JsonResponse({"posts": [_post_dict(p) for p in posts]})

    def post(self, request):
        data = _body(request)
        try:
            # Accept author_id or author_pk for backward compat
            author_id = data.get("author_id") or data.get("author_pk")
            post = Post.objects.create(
                title=data["title"],
                slug=data["slug"],
                body=data.get("body", ""),
                author_id=author_id,
                published=data.get("published", False),
                tags=data.get("tags", []),
            )
        except (KeyError, Exception) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_post_dict(post), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class PostDetailView(View):
    def _get_or_404(self, pk):
        try:
            return Post.objects.get(pk=pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        post = self._get_or_404(pk)
        if not post:
            return JsonResponse({"error": "Not found"}, status=404)
        post.view_count = (post.view_count or 0) + 1
        post.save()
        comments = [_comment_dict(c) for c in Comment.objects.filter(post_id=pk)]
        return JsonResponse({**_post_dict(post), "comments": comments})

    def put(self, request, pk):
        post = self._get_or_404(pk)
        if not post:
            return JsonResponse({"error": "Not found"}, status=404)
        data = _body(request)
        for field in ("title", "slug", "body", "published", "public", "tags"):
            if field in data:
                setattr(post, field, data[field])
        post.save()
        return JsonResponse(_post_dict(post))

    def delete(self, request, pk):
        post = self._get_or_404(pk)
        if not post:
            return JsonResponse({"error": "Not found"}, status=404)
        Comment.objects.filter(post_id=pk).delete()
        post.delete()
        return JsonResponse({}, status=204)


# ─────────────────────────────────────────────────────── Comment views

@method_decorator(csrf_exempt, name="dispatch")
class CommentCreateView(View):
    def post(self, request, post_pk):
        data = _body(request)
        try:
            Post.objects.get(pk=post_pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Post not found"}, status=404)
        try:
            comment = Comment.objects.create(
                post_id=post_pk,
                author_name=data["author_name"],
                body=data["body"],
                approved=data.get("approved", True),
            )
        except (KeyError, Exception) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_comment_dict(comment), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class CommentDeleteView(View):
    def delete(self, request, pk):
        try:
            comment = Comment.objects.get(pk=pk)
            comment.delete()
            return JsonResponse({}, status=204)
        except (Comment.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Not found"}, status=404)


# ───────────────────────── Posts-by-author  (GSI Query via ORM)


@method_decorator(csrf_exempt, name="dispatch")
class AuthorPostsView(View):
    """
    GET /api/authors/<pk>/posts/

    Returns posts for one author via ``Post.objects.filter(author_id=pk)``.
    The DynamoDB compiler detects that ``author_id`` carries a GSI and issues
    a DynamoDB Query (O(results)) instead of a full-table Scan.

    Query parameters
    ────────────────
    limit   int   Max items per page          (default 50, max 500)
    cursor  str   Opaque pagination token     (base64-encoded integer offset)

    Response
    ────────
    {
        "author_id": "...",
        "count": 47,
        "next_cursor": "NTA=",   ← null on last page
        "elapsed_ms": 12.4,
        "posts": [ { "pk": ..., "title": ..., ... }, ... ]
    }
    """

    _DEFAULT_LIMIT = 50
    _MAX_LIMIT = 500

    def get(self, request, pk):
        # ── Validate author PK ─────────────────────────────────────────
        try:
            author_id = str(uuid.UUID(pk))
        except ValueError:
            return JsonResponse({"error": "Invalid author pk"}, status=400)

        try:
            Author.objects.get(pk=pk)
        except (Author.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Author not found"}, status=404)

        # ── Parse query params ─────────────────────────────────────────
        try:
            limit = min(int(request.GET.get("limit", self._DEFAULT_LIMIT)),
                        self._MAX_LIMIT)
        except ValueError:
            limit = self._DEFAULT_LIMIT

        cursor_raw = request.GET.get("cursor")
        offset = 0
        if cursor_raw:
            try:
                offset = int(base64.urlsafe_b64decode(cursor_raw.encode()).decode())
            except Exception:
                return JsonResponse({"error": "Invalid cursor"}, status=400)

        # ── ORM query — compiler uses author_id-index GSI automatically ─
        t0   = time.perf_counter()
        page = list(Post.objects.filter(author_id=author_id)[offset : offset + limit])
        ms   = (time.perf_counter() - t0) * 1000

        # ── Build next cursor (offset-based) ───────────────────────────
        next_cursor = None
        if len(page) == limit:
            next_cursor = base64.urlsafe_b64encode(
                str(offset + limit).encode()
            ).decode()

        return JsonResponse({
            "author_id":   author_id,
            "count":       len(page),
            "next_cursor": next_cursor,
            "elapsed_ms":  round(ms, 2),
            "posts":       [_post_dict(p) for p in page],
        })


# ──────────────────────────────────────── Serializers for new models

def _profile_dict(p: AuthorProfile) -> dict:
    return {
        "pk": _str_pk(p.pk),
        "author_id": _str_pk(p.author_id),
        "website": p.website,
        "twitter": p.twitter,
        "location": p.location,
        "avatar_url": p.avatar_url,
        "follower_count": p.follower_count,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _tag_dict(t: Tag) -> dict:
    return {
        "pk": _str_pk(t.pk),
        "name": t.name,
        "slug": t.slug,
        "colour": t.colour,
    }


def _category_dict(c: Category) -> dict:
    return {
        "pk": _str_pk(c.pk),
        "name": c.name,
        "slug": c.slug,
        "parent_id": _str_pk(c.parent_id),
        "description": c.description,
    }


def _revision_dict(r: PostRevision) -> dict:
    return {
        "pk": _str_pk(r.pk),
        "post_id": _str_pk(r.post_id),
        "editor_id": _str_pk(r.editor_id),
        "body_snapshot": r.body_snapshot,
        "revision_number": r.revision_number,
        "change_summary": r.change_summary,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _postcategory_dict(pc: PostCategory) -> dict:
    return {
        "pk": _str_pk(pc.pk),
        "post_id": _str_pk(pc.post_id),
        "category_id": _str_pk(pc.category_id),
        "order": pc.order,
        "pinned": pc.pinned,
        "added_at": pc.added_at.isoformat() if pc.added_at else None,
    }


# ───────────────────────────────────────────── Author Profile views

@method_decorator(csrf_exempt, name="dispatch")
class AuthorProfileView(View):
    """GET/POST /api/authors/<pk>/profile/ — retrieve or upsert profile."""

    def _get_author_or_404(self, pk):
        try:
            return Author.objects.get(pk=pk)
        except (Author.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        author = self._get_author_or_404(pk)
        if not author:
            return JsonResponse({"error": "Author not found"}, status=404)
        try:
            profile = AuthorProfile.objects.get(author_id=pk)
            return JsonResponse(_profile_dict(profile))
        except AuthorProfile.DoesNotExist:
            return JsonResponse({"error": "Profile not found"}, status=404)

    def post(self, request, pk):
        author = self._get_author_or_404(pk)
        if not author:
            return JsonResponse({"error": "Author not found"}, status=404)
        data = _body(request)
        # Upsert — update existing or create new
        try:
            profile = AuthorProfile.objects.get(author_id=pk)
            created = False
        except AuthorProfile.DoesNotExist:
            profile = AuthorProfile(author=author)
            created = True
        for field in ("website", "twitter", "location", "avatar_url", "follower_count"):
            if field in data:
                setattr(profile, field, data[field])
        profile.save()
        return JsonResponse(_profile_dict(profile), status=201 if created else 200)


# ──────────────────────────────────────────────────────── Tag views

@method_decorator(csrf_exempt, name="dispatch")
class TagListView(View):
    def get(self, request):
        return JsonResponse({"tags": [_tag_dict(t) for t in Tag.objects.all()]})

    def post(self, request):
        data = _body(request)
        try:
            tag = Tag.objects.create(
                name=data["name"],
                slug=data.get("slug", data["name"].lower().replace(" ", "-")),
                colour=data.get("colour", "#cccccc"),
            )
        except (KeyError, Exception) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_tag_dict(tag), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class TagDetailView(View):
    def _get_or_404(self, pk):
        try:
            return Tag.objects.get(pk=pk)
        except (Tag.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        tag = self._get_or_404(pk)
        if not tag:
            return JsonResponse({"error": "Not found"}, status=404)
        return JsonResponse(_tag_dict(tag))

    def delete(self, request, pk):
        tag = self._get_or_404(pk)
        if not tag:
            return JsonResponse({"error": "Not found"}, status=404)
        tag.delete()
        return JsonResponse({}, status=204)


# ─────────────────────────────────────────────────── Category views

@method_decorator(csrf_exempt, name="dispatch")
class CategoryListView(View):
    def get(self, request):
        return JsonResponse({"categories": [_category_dict(c) for c in Category.objects.all()]})

    def post(self, request):
        data = _body(request)
        try:
            cat = Category.objects.create(
                name=data["name"],
                slug=data.get("slug", data["name"].lower().replace(" ", "-")),
                parent_id=data.get("parent_id"),
                description=data.get("description", ""),
            )
        except (KeyError, Exception) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_category_dict(cat), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class CategoryDetailView(View):
    def _get_or_404(self, pk):
        try:
            return Category.objects.get(pk=pk)
        except (Category.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        cat = self._get_or_404(pk)
        if not cat:
            return JsonResponse({"error": "Not found"}, status=404)
        children = [_category_dict(c) for c in Category.objects.filter(parent_id=pk)]
        data = _category_dict(cat)
        data["children"] = children
        return JsonResponse(data)

    def delete(self, request, pk):
        cat = self._get_or_404(pk)
        if not cat:
            return JsonResponse({"error": "Not found"}, status=404)
        cat.delete()
        return JsonResponse({}, status=204)


# ──────────────────────────────────────────── Post labels (M2M auto)

@method_decorator(csrf_exempt, name="dispatch")
class PostLabelsView(View):
    """GET / POST /api/posts/<pk>/labels/   — list or add tags."""

    def _get_post_or_404(self, pk):
        try:
            return Post.objects.get(pk=pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        return JsonResponse({"labels": [_tag_dict(t) for t in post.labels.all()]})

    def post(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        data = _body(request)
        tag_pk = data.get("tag_id")
        if not tag_pk:
            return JsonResponse({"error": "tag_id required"}, status=400)
        try:
            tag = Tag.objects.get(pk=tag_pk)
        except (Tag.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Tag not found"}, status=404)
        post.labels.add(tag)
        return JsonResponse({"labels": [_tag_dict(t) for t in post.labels.all()]})


@method_decorator(csrf_exempt, name="dispatch")
class PostLabelRemoveView(View):
    """DELETE /api/posts/<pk>/labels/<tag_pk>/"""

    def delete(self, request, pk, tag_pk):
        try:
            post = Post.objects.get(pk=pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Post not found"}, status=404)
        try:
            tag = Tag.objects.get(pk=tag_pk)
        except (Tag.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Tag not found"}, status=404)
        post.labels.remove(tag)
        return JsonResponse({"labels": [_tag_dict(t) for t in post.labels.all()]})


# ──────────────────────────── Post categories (explicit M2M through)

@method_decorator(csrf_exempt, name="dispatch")
class PostCategoriesView(View):
    """GET / POST /api/posts/<pk>/categories/ — list or assign categories."""

    def _get_post_or_404(self, pk):
        try:
            return Post.objects.get(pk=pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        pcs = [_postcategory_dict(pc) for pc in PostCategory.objects.filter(post_id=pk)]
        return JsonResponse({"post_categories": pcs})

    def post(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        data = _body(request)
        cat_pk = data.get("category_id")
        if not cat_pk:
            return JsonResponse({"error": "category_id required"}, status=400)
        try:
            cat = Category.objects.get(pk=cat_pk)
        except (Category.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Category not found"}, status=404)
        try:
            pc = PostCategory.objects.create(
                post=post,
                category=cat,
                order=data.get("order", 0),
                pinned=data.get("pinned", False),
            )
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_postcategory_dict(pc), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class PostCategoryDeleteView(View):
    """DELETE /api/postcategories/<pk>/"""

    def delete(self, request, pk):
        try:
            pc = PostCategory.objects.get(pk=pk)
            pc.delete()
            return JsonResponse({}, status=204)
        except (PostCategory.DoesNotExist, ValidationError, ValueError):
            return JsonResponse({"error": "Not found"}, status=404)


# ───────────────────────────────────────────────── Post revisions

@method_decorator(csrf_exempt, name="dispatch")
class PostRevisionsView(View):
    """GET / POST /api/posts/<pk>/revisions/"""

    def _get_post_or_404(self, pk):
        try:
            return Post.objects.get(pk=pk)
        except (Post.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        revs = [_revision_dict(r) for r in PostRevision.objects.filter(post_id=pk)]
        return JsonResponse({"revisions": revs})

    def post(self, request, pk):
        post = self._get_post_or_404(pk)
        if not post:
            return JsonResponse({"error": "Post not found"}, status=404)
        data = _body(request)
        editor_id = data.get("editor_id")
        rev_num = (PostRevision.objects.filter(post_id=pk).count() or 0) + 1
        try:
            rev = PostRevision.objects.create(
                post=post,
                editor_id=editor_id or None,
                body_snapshot=data.get("body_snapshot", post.body),
                revision_number=rev_num,
                change_summary=data.get("change_summary", ""),
            )
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(_revision_dict(rev), status=201)


# ────────────────────────────────────────────────── Explorer UI

class ExplorerView(View):
    """Serve the single-page HTML explorer at /explorer/."""

    def get(self, request):
        return render(request, "demo_app/explorer.html")
