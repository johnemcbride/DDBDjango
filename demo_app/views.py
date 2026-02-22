"""
demo_app.views
~~~~~~~~~~~~~~
Simple JSON REST views for the Blog demo.
No DRF required — uses plain Django JsonResponse.

Endpoints:
    GET  /api/authors/                  list authors
    POST /api/authors/                  create author
    GET  /api/authors/<pk>/             retrieve author
    PUT  /api/authors/<pk>/             update author
    DELETE /api/authors/<pk>/           delete author

    GET  /api/posts/                    list posts (optionally ?author_id=)
    POST /api/posts/                    create post
    GET  /api/posts/<pk>/               retrieve post + comments
    PUT  /api/posts/<pk>/               update post
    DELETE /api/posts/<pk>/             delete post

    POST /api/posts/<pk>/comments/      add comment
    DELETE /api/comments/<pk>/          delete comment
"""

import json
import os
import time
import uuid
import base64

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Author, Post, Comment


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


# ─────────────────────────────────────── Posts-by-author  (GSI Query)

def _get_dynamo_table(table_name: str):
    """
    Return a boto3 DynamoDB Table resource using the same config as the
    Django DATABASES['dynamodb'] entry.  Bypasses the ORM for direct
    high-throughput reads / writes.
    """
    import boto3
    from django.conf import settings
    db = settings.DATABASES["default"]
    endpoint = os.environ.get("DYNAMO_ENDPOINT_URL") or db.get("ENDPOINT_URL") or ""
    opts = dict(
        region_name=db.get("REGION", "us-east-1"),
        aws_access_key_id=db.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=db.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    if endpoint:
        opts["endpoint_url"] = endpoint
    prefix = db.get("OPTIONS", {}).get("table_prefix", "")
    dynamo = boto3.resource("dynamodb", **opts)
    return dynamo.Table(f"{prefix}{table_name}")


@method_decorator(csrf_exempt, name="dispatch")
class AuthorPostsView(View):
    """
    GET /api/authors/<pk>/posts/

    Returns posts by a single author using a direct DynamoDB Query against
    the ``author_id-index`` GSI — O(results) not O(table size).

    Query parameters
    ────────────────
    limit   int   Max items per page         (default 50, max 500)
    cursor  str   Opaque pagination token    (base64-encoded LastEvaluatedKey)

    Response
    ────────
    {
        "author_id": "...",
        "count": 47,
        "next_cursor": "eyJpZCI6Li4ufQ==",   ← null on last page
        "elapsed_ms": 12.4,
        "posts": [ { "pk": ..., "title": ..., ... }, ... ]
    }
    """

    _DEFAULT_LIMIT = 50
    _MAX_LIMIT = 500
    _GSI_NAME = "author_id-index"

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
        start_key  = None
        if cursor_raw:
            try:
                start_key = json.loads(
                    base64.urlsafe_b64decode(cursor_raw.encode()).decode()
                )
            except Exception:
                return JsonResponse({"error": "Invalid cursor"}, status=400)

        # ── DynamoDB GSI Query ─────────────────────────────────────────
        from boto3.dynamodb.conditions import Key

        table = _get_dynamo_table("demo_app_post")

        query_kwargs: dict = {
            "IndexName": self._GSI_NAME,
            "KeyConditionExpression": Key("author_id").eq(author_id),
            "Limit": limit,
        }
        if start_key:
            query_kwargs["ExclusiveStartKey"] = start_key

        t0   = time.perf_counter()
        resp = table.query(**query_kwargs)
        ms   = (time.perf_counter() - t0) * 1000

        # ── Build next cursor ──────────────────────────────────────────
        last_key    = resp.get("LastEvaluatedKey")
        next_cursor = None
        if last_key:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(last_key).encode()
            ).decode()

        # ── Serialise items ────────────────────────────────────────────
        posts = []
        for item in resp.get("Items", []):
            posts.append({
                "pk":         item.get("id", ""),
                "author_id":  item.get("author_id", ""),
                "title":      item.get("title", ""),
                "slug":       item.get("slug", ""),
                "published":  item.get("published", False),
                "public":     item.get("public", True),
                "tags":       item.get("tags", []),
                "view_count": int(item.get("view_count", 0)),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            })

        return JsonResponse({
            "author_id":   author_id,
            "count":       len(posts),
            "next_cursor": next_cursor,
            "elapsed_ms":  round(ms, 2),
            "posts":       posts,
        })
