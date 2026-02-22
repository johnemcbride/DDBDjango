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

    GET  /api/posts/                    list posts (optionally ?author_pk=)
    POST /api/posts/                    create post
    GET  /api/posts/<pk>/               retrieve post + comments
    PUT  /api/posts/<pk>/               update post
    DELETE /api/posts/<pk>/             delete post

    POST /api/posts/<pk>/comments/      add comment
    DELETE /api/comments/<pk>/          delete comment
"""

import json

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


def _author_dict(a: Author) -> dict:
    return {
        "pk": a.pk,
        "username": a.username,
        "email": a.email,
        "bio": a.bio,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _post_dict(p: Post) -> dict:
    return {
        "pk": p.pk,
        "title": p.title,
        "slug": p.slug,
        "body": p.body,
        "author_pk": p.author_pk,
        "published": p.published,
        "public": p.public,
        "tags": p.tags or [],
        "view_count": p.view_count,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _comment_dict(c: Comment) -> dict:
    return {
        "pk": c.pk,
        "post_pk": c.post_pk,
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
        except Author.DoesNotExist:
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
        author_pk = request.GET.get("author_pk")
        if author_pk:
            posts = Post.objects.filter(author_pk=author_pk)
        else:
            posts = Post.objects.all()
        return JsonResponse({"posts": [_post_dict(p) for p in posts]})

    def post(self, request):
        data = _body(request)
        try:
            post = Post.objects.create(
                title=data["title"],
                slug=data["slug"],
                body=data.get("body", ""),
                author_pk=data.get("author_pk", ""),
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
        except Post.DoesNotExist:
            return None

    def get(self, request, pk):
        post = self._get_or_404(pk)
        if not post:
            return JsonResponse({"error": "Not found"}, status=404)
        # Increment view count
        post.view_count = (post.view_count or 0) + 1
        post.save()
        comments = [_comment_dict(c) for c in Comment.objects.filter(post_pk=pk)]
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
        Comment.objects.filter(post_pk=pk).delete()
        post.delete()
        return JsonResponse({}, status=204)


# ─────────────────────────────────────────────────────── Comment views

@method_decorator(csrf_exempt, name="dispatch")
class CommentCreateView(View):
    def post(self, request, post_pk):
        data = _body(request)
        try:
            Post.objects.get(pk=post_pk)
        except Post.DoesNotExist:
            return JsonResponse({"error": "Post not found"}, status=404)
        try:
            comment = Comment.objects.create(
                post_pk=post_pk,
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
        except Comment.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)
