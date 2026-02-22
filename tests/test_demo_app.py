"""
tests/test_demo_app.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for the Blog demo-app models and HTTP views.

Uses standard Django ORM against moto-mocked DynamoDB.
ForeignKey fields are used instead of raw string PK fields.
"""

import json
import pytest

from django.test import Client

from demo_app.models import Author, Post, Comment


# ══════════════════════════════════════════════════════ model tests

@pytest.mark.usefixtures("mock_dynamodb")
class TestAuthorModel:
    def test_create_and_retrieve(self):
        a = Author.objects.create(username="jdoe", email="jdoe@example.com")
        assert a.pk is not None
        fetched = Author.objects.get(pk=a.pk)
        assert fetched.username == "jdoe"
        assert fetched.email == "jdoe@example.com"

    def test_filter_by_username(self):
        Author.objects.create(username="alice", email="alice@x.com")
        Author.objects.create(username="bob",   email="bob@x.com")
        results = list(Author.objects.filter(username="alice"))
        assert len(results) == 1
        assert results[0].username == "alice"

    def test_update(self):
        a = Author.objects.create(username="before")
        a.username = "after"
        a.save()
        assert Author.objects.get(pk=a.pk).username == "after"

    def test_delete(self):
        a = Author.objects.create(username="gone")
        pk = a.pk
        a.delete()
        with pytest.raises(Author.DoesNotExist):
            Author.objects.get(pk=pk)

    def test_created_at_auto_set(self):
        from datetime import datetime
        a = Author.objects.create(username="timed")
        assert isinstance(a.created_at, datetime)

    def test_all_returns_multiple(self):
        Author.objects.create(username="u1")
        Author.objects.create(username="u2")
        assert Author.objects.count() >= 2

    def test_str(self):
        a = Author.objects.create(username="strtest")
        assert str(a) == "strtest"


@pytest.mark.usefixtures("mock_dynamodb")
class TestPostModel:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_dynamodb):
        self.author = Author.objects.create(username="writer", email="w@x.com")

    def test_create_post(self):
        p = Post.objects.create(
            title="Hello World",
            slug="hello-world",
            author=self.author,
        )
        assert Post.objects.get(pk=p.pk).title == "Hello World"

    def test_default_published_false(self):
        p = Post.objects.create(title="Draft", slug="draft", author=self.author)
        assert p.published is False

    def test_tags_list(self):
        p = Post.objects.create(
            title="Tagged", slug="tagged",
            author=self.author, tags=["python", "aws"],
        )
        fetched = Post.objects.get(pk=p.pk)
        assert "python" in fetched.tags

    def test_post_author_fk(self):
        """ForeignKey should resolve to the Author instance."""
        p = Post.objects.create(title="T", slug="t", author=self.author)
        assert p.author_id == self.author.pk

    def test_filter_by_author_id(self):
        other = Author.objects.create(username="other")
        Post.objects.create(title="Mine",  slug="mine",  author=self.author)
        Post.objects.create(title="Other", slug="other", author=other)
        results = list(Post.objects.filter(author_id=self.author.pk))
        assert len(results) == 1
        assert results[0].title == "Mine"

    def test_updated_at_changes_on_save(self):
        import time
        p = Post.objects.create(title="T", slug="t", author=self.author)
        first = p.updated_at
        time.sleep(0.05)
        p.title = "T2"
        p.save()
        p.refresh_from_db()
        assert p.updated_at >= first

    def test_str(self):
        p = Post.objects.create(title="My Post", slug="my-post", author=self.author)
        assert str(p) == "My Post"


@pytest.mark.usefixtures("mock_dynamodb")
class TestCommentModel:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_dynamodb):
        author = Author.objects.create(username="commenter")
        self.post = Post.objects.create(title="T", slug="t", author=author)

    def test_create_comment(self):
        c = Comment.objects.create(
            post=self.post,
            author_name="Reader",
            body="Great post!",
        )
        assert Comment.objects.get(pk=c.pk).body == "Great post!"

    def test_comment_post_fk(self):
        """post_id should equal the post's pk."""
        c = Comment.objects.create(post=self.post, author_name="X", body="Y")
        assert c.post_id == self.post.pk

    def test_filter_by_post_id(self):
        other_post = Post.objects.create(
            title="Other", slug="other", author=self.post.author
        )
        Comment.objects.create(post=self.post, author_name="A", body="On post")
        Comment.objects.create(post=other_post, author_name="B", body="On other")
        results = list(Comment.objects.filter(post_id=self.post.pk))
        assert len(results) == 1
        assert results[0].author_name == "A"

    def test_approved_default_true(self):
        c = Comment.objects.create(post=self.post, author_name="R", body="!")
        assert c.approved is True


# ══════════════════════════════════════════════════════ view tests

@pytest.fixture
def client():
    return Client()


@pytest.mark.usefixtures("mock_dynamodb")
class TestAuthorViews:
    def test_list_empty(self, client):
        resp = client.get("/api/authors/")
        assert resp.status_code == 200
        assert resp.json()["authors"] == []

    def test_create(self, client):
        resp = client.post(
            "/api/authors/",
            data=json.dumps({"username": "alice", "email": "a@x.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "alice"
        assert "pk" in data

    def test_create_missing_username(self, client):
        resp = client.post(
            "/api/authors/",
            data=json.dumps({"email": "nousername@x.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_retrieve(self, client):
        a = Author.objects.create(username="bob", email="b@x.com")
        resp = client.get(f"/api/authors/{a.pk}/")
        assert resp.status_code == 200
        assert resp.json()["pk"] == str(a.pk)

    def test_retrieve_not_found(self, client):
        resp = client.get("/api/authors/does-not-exist/")
        assert resp.status_code == 404

    def test_update(self, client):
        a = Author.objects.create(username="old")
        resp = client.put(
            f"/api/authors/{a.pk}/",
            data=json.dumps({"username": "new"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "new"

    def test_delete(self, client):
        a = Author.objects.create(username="todelete")
        resp = client.delete(f"/api/authors/{a.pk}/")
        assert resp.status_code == 204
        with pytest.raises(Author.DoesNotExist):
            Author.objects.get(pk=a.pk)

    def test_list_returns_all(self, client):
        Author.objects.create(username="u1")
        Author.objects.create(username="u2")
        resp = client.get("/api/authors/")
        assert len(resp.json()["authors"]) >= 2


@pytest.mark.usefixtures("mock_dynamodb")
class TestPostViews:
    def _author(self):
        return Author.objects.create(username="writer", email="w@x.com")

    def test_create_post(self, client):
        a = self._author()
        resp = client.post(
            "/api/posts/",
            data=json.dumps({"title": "T", "slug": "t", "author_id": str(a.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "T"

    def test_list_posts(self, client):
        a = self._author()
        Post.objects.create(title="P1", slug="p1", author=a)
        Post.objects.create(title="P2", slug="p2", author=a)
        resp = client.get("/api/posts/")
        assert len(resp.json()["posts"]) >= 2

    def test_list_filter_by_author(self, client):
        a = self._author()
        other = Author.objects.create(username="other")
        Post.objects.create(title="Mine",  slug="mine",  author=a)
        Post.objects.create(title="Other", slug="other", author=other)
        resp = client.get(f"/api/posts/?author_id={a.pk}")
        posts = resp.json()["posts"]
        assert len(posts) == 1
        assert posts[0]["title"] == "Mine"

    def test_retrieve_increments_views(self, client):
        a = self._author()
        p = Post.objects.create(title="T", slug="t", author=a)
        client.get(f"/api/posts/{p.pk}/")
        resp = client.get(f"/api/posts/{p.pk}/")
        assert resp.json()["view_count"] >= 1

    def test_retrieve_includes_comments(self, client):
        a = self._author()
        p = Post.objects.create(title="T", slug="t", author=a)
        Comment.objects.create(post=p, author_name="R", body="Nice!")
        resp = client.get(f"/api/posts/{p.pk}/")
        assert len(resp.json()["comments"]) == 1

    def test_update_post(self, client):
        a = self._author()
        p = Post.objects.create(title="Old", slug="old", author=a)
        resp = client.put(
            f"/api/posts/{p.pk}/",
            data=json.dumps({"title": "New", "published": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"
        assert resp.json()["published"] is True

    def test_delete_post_cascades_comments(self, client):
        a = self._author()
        p = Post.objects.create(title="T", slug="t", author=a)
        c = Comment.objects.create(post=p, author_name="R", body="!")
        resp = client.delete(f"/api/posts/{p.pk}/")
        assert resp.status_code == 204
        with pytest.raises(Comment.DoesNotExist):
            Comment.objects.get(pk=c.pk)

    def test_post_not_found(self, client):
        resp = client.get("/api/posts/ghost/")
        assert resp.status_code == 404


@pytest.mark.usefixtures("mock_dynamodb")
class TestCommentViews:
    def _setup(self):
        a = Author.objects.create(username="w")
        p = Post.objects.create(title="T", slug="t", author=a)
        return a, p

    def test_create_comment(self, client):
        _, p = self._setup()
        resp = client.post(
            f"/api/posts/{p.pk}/comments/",
            data=json.dumps({"author_name": "Reader", "body": "Awesome!"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["body"] == "Awesome!"

    def test_create_comment_post_not_found(self, client):
        resp = client.post(
            "/api/posts/nonexistent/comments/",
            data=json.dumps({"author_name": "R", "body": "B"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_delete_comment(self, client):
        _, p = self._setup()
        c = Comment.objects.create(post=p, author_name="R", body="B")
        resp = client.delete(f"/api/comments/{c.pk}/")
        assert resp.status_code == 204
        with pytest.raises(Comment.DoesNotExist):
            Comment.objects.get(pk=c.pk)

    def test_delete_comment_not_found(self, client):
        resp = client.delete("/api/comments/ghost/")
        assert resp.status_code == 404
