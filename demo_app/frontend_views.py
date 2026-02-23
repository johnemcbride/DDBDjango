"""
demo_app.frontend_views
~~~~~~~~~~~~~~~~~~~~~~~
Template-based views for the blog frontend.
These are separate from the /api/ JSON views in views.py.

Routes (all served at the site root, not under /api/):
    /                           home — paginated post feed
    /posts/<pk>/                post detail + comments
    /posts/<pk>/comment/        POST-only, add comment, redirects back
    /write/                     create a new post (GET form + POST submit)
    /authors/<pk>/              author profile + posts
    /tags/<slug>/               posts labelled with a tag
    /categories/<slug>/         posts in a category
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.utils.text import slugify
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from .models import (
    Author, Post, Comment, Tag, Category, AuthorProfile, PostRevision, PostCategory
)

PAGE_SIZE = 10


# ─────────────────────────────────────────────────────────── helpers

def _published_posts():
    """Return all posts that are published and public, newest first."""
    return (
        Post.objects.filter(published=True, public=True)
        .order_by("-created_at")
    )


def _enrich_post(post):
    """Attach labels, categories, author to a post in-place."""
    post.label_list = list(post.labels.all())
    post.post_category_list = list(
        PostCategory.objects.filter(post_id=post.pk).order_by("order")
    )
    post.category_list = []
    for pc in post.post_category_list:
        try:
            post.category_list.append(Category.objects.get(pk=pc.category_id))
        except Category.DoesNotExist:
            pass
    try:
        post.author_obj = Author.objects.get(pk=post.author_id)
    except Author.DoesNotExist:
        post.author_obj = None
    return post


# ───────────────────────────────────────────────────────────── Home

class HomeView(View):
    def get(self, request):
        tag_slug = request.GET.get("tag", "").strip()
        cat_slug = request.GET.get("category", "").strip()
        q = request.GET.get("q", "").strip()

        active_tag = None
        active_cat = None

        posts_qs = _published_posts()

        # Filter by tag label (M2M auto)
        if tag_slug:
            try:
                active_tag = Tag.objects.get(slug=tag_slug)
                tagged_post_ids = {
                    p.pk for p in active_tag.posts.filter(published=True, public=True)
                }
                posts_qs = [p for p in posts_qs if p.pk in tagged_post_ids]
            except Tag.DoesNotExist:
                posts_qs = []

        # Filter by category (explicit M2M through)
        elif cat_slug:
            try:
                active_cat = Category.objects.get(slug=cat_slug)
                cat_post_ids = {
                    pc.post_id
                    for pc in PostCategory.objects.filter(category_id=active_cat.pk)
                }
                posts_qs = [p for p in posts_qs if p.pk in cat_post_ids]
            except Category.DoesNotExist:
                posts_qs = []

        # Simple title/body keyword search
        if q:
            ql = q.lower()
            posts_qs = [
                p for p in posts_qs
                if ql in p.title.lower() or ql in p.body.lower()
            ]

        posts = list(posts_qs)

        # Pagination
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (ValueError, TypeError):
            page = 1
        total = len(posts)
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_posts = [_enrich_post(p) for p in posts[start:end]]

        all_tags = list(Tag.objects.all())
        all_cats_flat = list(Category.objects.all())
        # Build a simple tree: root categories with their children attached
        cat_map = {str(c.pk): c for c in all_cats_flat}
        root_cats = []
        for c in all_cats_flat:
            c.child_list = []
        for c in all_cats_flat:
            parent_id = str(c.parent_id) if c.parent_id else None
            if parent_id and parent_id in cat_map:
                cat_map[parent_id].child_list.append(c)
            else:
                root_cats.append(c)

        return render(request, "demo_app/home.html", {
            "posts": page_posts,
            "page": page,
            "total": total,
            "has_prev": page > 1,
            "has_next": end < total,
            "all_tags": all_tags,
            "all_cats": root_cats,
            "active_tag": active_tag,
            "active_cat": active_cat,
            "q": q,
        })


# ───────────────────────────────────────────────────────── Post detail

class PostDetailView(View):
    def get(self, request, pk):
        try:
            post = Post.objects.get(pk=pk)
        except Post.DoesNotExist:
            from django.http import Http404
            raise Http404

        # Increment view count
        post.view_count = (post.view_count or 0) + 1
        post.save()

        _enrich_post(post)
        comments = list(
            Comment.objects.filter(post_id=pk, approved=True).order_by("created_at")
        )
        revisions = list(
            PostRevision.objects.filter(post_id=pk).order_by("revision_number")
        )
        for rev in revisions:
            if rev.editor_id:
                try:
                    rev.editor_obj = Author.objects.get(pk=rev.editor_id)
                except Author.DoesNotExist:
                    rev.editor_obj = None
            else:
                rev.editor_obj = None

        # Related posts: same labels or categories
        related = []
        if post.label_list:
            for tag in post.label_list[:2]:
                for rp in tag.posts.filter(published=True, public=True)[:8]:
                    if rp.pk != post.pk and rp not in related:
                        related.append(rp)
                        if len(related) >= 4:
                            break
                if len(related) >= 4:
                    break

        return render(request, "demo_app/post_detail.html", {
            "post": post,
            "comments": comments,
            "revisions": revisions,
            "related": related[:4],
        })


class AddCommentView(View):
    def post(self, request, pk):
        try:
            post = Post.objects.get(pk=pk)
        except Post.DoesNotExist:
            from django.http import Http404
            raise Http404

        name = request.POST.get("author_name", "").strip()
        body = request.POST.get("body", "").strip()
        if not body:
            messages.error(request, "Comment body cannot be empty.")
        else:
            Comment.objects.create(
                post=post,
                author_name=name or "Anonymous",
                body=body,
                approved=True,
            )
            messages.success(request, "Comment added!")
        return redirect("post-detail", pk=pk)


# ───────────────────────────────────────────────────────── Author profile

class AuthorDetailView(View):
    def get(self, request, pk):
        try:
            author = Author.objects.get(pk=pk)
        except Author.DoesNotExist:
            from django.http import Http404
            raise Http404

        try:
            profile = AuthorProfile.objects.get(author_id=pk)
        except AuthorProfile.DoesNotExist:
            profile = None

        posts = list(
            Post.objects.filter(author_id=pk, published=True, public=True)
            .order_by("-created_at")[:20]
        )
        for p in posts:
            p.label_list = list(p.labels.all())

        return render(request, "demo_app/author_detail.html", {
            "author": author,
            "profile": profile,
            "posts": posts,
        })


# ───────────────────────────────────────────────────────── Tag detail

class TagDetailView(View):
    def get(self, request, slug):
        try:
            tag = Tag.objects.get(slug=slug)
        except Tag.DoesNotExist:
            from django.http import Http404
            raise Http404

        posts = list(
            tag.posts.filter(published=True, public=True).order_by("-created_at")[:30]
        )
        for p in posts:
            p.label_list = list(p.labels.all())
            try:
                p.author_obj = Author.objects.get(pk=p.author_id)
            except Author.DoesNotExist:
                p.author_obj = None

        all_tags = list(Tag.objects.all())

        return render(request, "demo_app/tag_detail.html", {
            "tag": tag,
            "posts": posts,
            "all_tags": all_tags,
        })


# ───────────────────────────────────────────────────────── Category detail

class CategoryDetailView(View):
    def get(self, request, slug):
        try:
            cat = Category.objects.get(slug=slug)
        except Category.DoesNotExist:
            from django.http import Http404
            raise Http404

        subcats = list(Category.objects.filter(parent_id=cat.pk))
        post_ids = [
            pc.post_id
            for pc in PostCategory.objects.filter(category_id=cat.pk).order_by("order")
        ]
        posts = []
        for pid in post_ids:
            try:
                p = Post.objects.get(pk=pid)
                if p.published and p.public:
                    p.label_list = list(p.labels.all())
                    try:
                        p.author_obj = Author.objects.get(pk=p.author_id)
                    except Author.DoesNotExist:
                        p.author_obj = None
                    posts.append(p)
            except Post.DoesNotExist:
                pass

        breadcrumb = []
        cur = cat
        while cur:
            breadcrumb.insert(0, cur)
            if cur.parent_id:
                try:
                    cur = Category.objects.get(pk=cur.parent_id)
                except Category.DoesNotExist:
                    break
            else:
                break

        return render(request, "demo_app/category_detail.html", {
            "cat": cat,
            "subcats": subcats,
            "posts": posts,
            "breadcrumb": breadcrumb,
        })


# ───────────────────────────────────────────────────────── Write / create post

class WritePostView(View):
    def get(self, request):
        authors = list(Author.objects.all())
        tags = list(Tag.objects.all())
        categories = list(Category.objects.all())
        return render(request, "demo_app/write_post.html", {
            "authors": authors,
            "tags": tags,
            "categories": categories,
        })

    def post(self, request):
        title = request.POST.get("title", "").strip()
        author_id = request.POST.get("author_id", "").strip()
        body = request.POST.get("body", "").strip()
        published = request.POST.get("published") == "on"
        post_slug = request.POST.get("slug", "").strip() or slugify(title)
        tag_ids = request.POST.getlist("label_ids")
        category_ids = request.POST.getlist("category_ids")

        errors = []
        if not title:
            errors.append("Title is required.")
        if not author_id:
            errors.append("Author is required.")

        author = None
        if author_id:
            try:
                author = Author.objects.get(pk=author_id)
            except Author.DoesNotExist:
                errors.append("Selected author does not exist.")

        if errors:
            messages.error(request, " ".join(errors))
            return redirect("write-post")

        post = Post.objects.create(
            title=title,
            slug=post_slug,
            author=author,
            body=body,
            published=published,
            public=True,
        )

        # Set labels (auto M2M)
        if tag_ids:
            tags = list(Tag.objects.filter(pk__in=tag_ids))
            post.labels.set(tags)

        # Set categories (explicit M2M through PostCategory)
        for i, cat_id in enumerate(category_ids):
            try:
                cat = Category.objects.get(pk=cat_id)
                PostCategory.objects.create(post=post, category=cat, order=i)
            except Category.DoesNotExist:
                pass

        messages.success(request, f'Post "{post.title}" created!')
        return redirect("post-detail", pk=post.pk)
