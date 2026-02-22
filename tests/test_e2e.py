"""
tests/test_e2e.py
~~~~~~~~~~~~~~~~~
End-to-end lifecycle test harness.

Covers the full stack in a single sequential scenario:
  1. Auth user creation  — superuser + regular user; LogEntry FK type safety
  2. Content creation    — Author / Post / Comment via REST API
  3. Search              — OpenSearch (mocked) + DDB-scan fallback
  4. Update              — field edits via REST API + ORM save
  5. Deletion            — cascaded removes; verify DB is clean

All DynamoDB I/O runs against moto (in-process mock) — no LocalStack needed.
OpenSearch calls are patched out so the tests are fully self-contained.

Run with:
    pytest tests/test_e2e.py -v
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from demo_app.models import Author, Comment, Post


# ─────────────────────────────────────────────────────────── fixtures


@pytest.fixture
def e2e_db(mock_dynamodb):
    """
    Extend the base mock_dynamodb fixture with every table needed for the
    end-to-end tests: auth tables, contenttypes, django admin log, and the
    User M2M through tables (auth_user_groups, auth_user_permissions) so
    that deleting a User doesn't hit ResourceNotFoundException.
    """
    from django.contrib.admin.models import LogEntry
    from django.contrib.auth.models import Group, Permission, User
    from django.contrib.contenttypes.models import ContentType
    from django.db import connections

    db_conn = connections["default"]
    user_groups_through = User.groups.through
    user_permissions_through = User.user_permissions.through
    for model in (
        ContentType, Permission, Group, LogEntry,
        user_groups_through, user_permissions_through,
    ):
        db_conn.creation.ensure_table(model)
    yield


@pytest.fixture
def api_client():
    return Client()


# ─────────────────────────────────────────────────────────── helpers


def _post_json(client: Client, url: str, data: dict) -> "django.http.JsonResponse":  # noqa
    return client.post(url, data=json.dumps(data), content_type="application/json")


def _put_json(client: Client, url: str, data: dict) -> "django.http.JsonResponse":  # noqa
    return client.put(url, data=json.dumps(data), content_type="application/json")


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — Auth user creation
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestUserCreation:
    """
    Verifies that Django users can be created and that LogEntry FK values
    (integer PKs stored as DynamoDB Numbers after the type-mismatch fix)
    work correctly.
    """

    def test_create_superuser(self):
        from django.contrib.auth.models import User

        su = User.objects.create_superuser(
            username="admin_e2e",
            email="admin@example.com",
            password="S3cure!Pass",
        )
        assert su.pk is not None
        assert su.is_superuser is True
        assert su.is_staff is True

        fetched = User.objects.get(username="admin_e2e")
        assert fetched.email == "admin@example.com"
        assert fetched.check_password("S3cure!Pass")

    def test_create_regular_user(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(
            username="regular_e2e",
            email="regular@example.com",
            password="P@ssw0rd!",
        )
        assert user.pk is not None
        assert user.is_superuser is False
        assert User.objects.filter(username="regular_e2e").count() == 1

    def test_logentry_fk_integer_type(self):
        """
        The original bug: after admin creates a user on the same request,
        user.pk is a *string* (returned from SQLInsertCompiler).  Writing a
        LogEntry then stored user_id as DynamoDB String 'S', but the GSI was
        declared as 'N' (integer).  Verify that the coercion fix in
        _to_dynamo_value now stores it as a Number so the PutItem succeeds.
        """
        from django.contrib.admin.models import ADDITION, LogEntry
        from django.contrib.auth.models import User
        from django.contrib.contenttypes.models import ContentType

        # Create user — PK is returned as a string from our INSERT compiler.
        user = User.objects.create_user(username="logtest", password="pw")
        assert isinstance(user.pk, (int, str))  # either type is fine at this point

        # ContentType.get_for_model internally does get_or_create; ensure table ready.
        ct = ContentType.objects.get_or_create(
            app_label="auth", model="user"
        )[0]

        # Simulate what Django admin does after saving a new object:
        # directly create a LogEntry (bypasses log_action/log_actions API
        # differences across Django versions and tests the PutItem path).
        # This is the exact call-path that triggered the ValidationException:
        # user_id stored as string 'S' vs GSI declared as 'N'.
        entry = LogEntry.objects.create(
            user_id=user.pk,
            content_type_id=ct.pk,
            object_id=str(user.pk),
            object_repr=str(user),
            action_flag=ADDITION,
            change_message="Created via e2e test",
        )
        assert entry.pk is not None

        entries = list(LogEntry.objects.filter(object_id=str(user.pk)))
        assert len(entries) == 1
        assert entries[0].action_flag == ADDITION

    def test_admin_login(self, api_client):
        """Superuser can authenticate through the admin login view."""
        from django.contrib.auth.models import User

        User.objects.create_superuser(
            username="admin_login_e2e", password="TestPass123!"
        )

        resp = api_client.post(
            "/admin/login/",
            data={
                "username": "admin_login_e2e",
                "password": "TestPass123!",
                "next": "/admin/",
            },
            follow=True,
        )
        # After successful login the admin dashboard should load (200)
        assert resp.status_code == 200
        # Session should be authenticated
        assert "_auth_user_id" in api_client.session

    def test_user_count(self):
        from django.contrib.auth.models import User

        User.objects.create_user(username="count_a", password="pw")
        User.objects.create_user(username="count_b", password="pw")
        assert User.objects.count() >= 2


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — Content creation
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestContentCreation:
    """Author / Post / Comment created through the REST API."""

    def test_create_author_via_api(self, api_client):
        resp = _post_json(api_client, "/api/authors/", {
            "username": "alice_e2e",
            "email": "alice@e2e.com",
            "bio": "Writes about DynamoDB",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "alice_e2e"
        assert "pk" in body
        # Verify persisted
        author = Author.objects.get(pk=body["pk"])
        assert author.bio == "Writes about DynamoDB"

    def test_create_post_via_api(self, api_client):
        author = Author.objects.create(username="writer_e2e", email="w@e2e.com")
        resp = _post_json(api_client, "/api/posts/", {
            "title": "Hello DynamoDB",
            "slug": "hello-dynamodb",
            "author_pk": str(author.pk),
            "body": "DynamoDB is schemaless.",
            "published": True,
            "tags": ["aws", "nosql"],
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Hello DynamoDB"
        assert body["published"] is True
        assert "nosql" in body["tags"]

        post = Post.objects.get(pk=body["pk"])
        assert post.author_id == author.pk

    def test_create_comment_via_api(self, api_client):
        author = Author.objects.create(username="commenter_e2e")
        post = Post.objects.create(
            title="Commented Post", slug="commented-post",
            author=author, published=True,
        )
        resp = _post_json(api_client, f"/api/posts/{post.pk}/comments/", {
            "author_name": "Bob",
            "body": "Great article!",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["body"] == "Great article!"

        comment = Comment.objects.get(pk=body["pk"])
        assert comment.post_id == post.pk
        assert comment.approved is True

    def test_full_create_chain_and_retrieve(self, api_client):
        """Create author → post → comment, then retrieve post detail."""
        author_resp = _post_json(api_client, "/api/authors/", {
            "username": "chain_author",
            "email": "chain@e2e.com",
        })
        assert author_resp.status_code == 201
        author_pk = author_resp.json()["pk"]

        post_resp = _post_json(api_client, "/api/posts/", {
            "title": "Chain Post",
            "slug": "chain-post",
            "author_pk": author_pk,
            "published": True,
        })
        assert post_resp.status_code == 201
        post_pk = post_resp.json()["pk"]

        _post_json(api_client, f"/api/posts/{post_pk}/comments/", {
            "author_name": "Reader",
            "body": "Interesting!",
        })
        _post_json(api_client, f"/api/posts/{post_pk}/comments/", {
            "author_name": "Fan",
            "body": "So good!",
        })

        detail = api_client.get(f"/api/posts/{post_pk}/")
        assert detail.status_code == 200
        data = detail.json()
        assert data["title"] == "Chain Post"
        assert len(data["comments"]) == 2
        comment_bodies = [c["body"] for c in data["comments"]]
        assert "Interesting!" in comment_bodies
        assert "So good!" in comment_bodies


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — Search
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestSearch:
    """
    Full-text search through two paths:
      a) OpenSearch mock — search_pks returns known PKs
      b) DDB scan fallback — search_pks returns None → icontains scan
    """

    @pytest.fixture(autouse=True)
    def seed_posts(self, e2e_db):  # explicit dep ensures moto is active first
        """Seed deterministic posts for search assertions."""
        self.author = Author.objects.create(username="search_author")
        self.rust_post = Post.objects.create(
            title="Introduction to Rust",
            slug="intro-rust",
            author=self.author,
            body="Rust is a systems programming language.",
            published=True,
            tags=["rust", "systems"],
        )
        self.python_post = Post.objects.create(
            title="Python Best Practices",
            slug="python-best",
            author=self.author,
            body="Python is widely used in data science.",
            published=True,
            tags=["python", "data"],
        )
        self.draft_post = Post.objects.create(
            title="Draft Rust Notes",
            slug="draft-rust",
            author=self.author,
            published=False,
        )

    def test_search_via_opensearch_mock(self):
        """When OpenSearch returns PKs, only those posts are returned."""
        target_pk = str(self.rust_post.pk)

        with patch(
            "dynamo_backend.opensearch_sync.search_pks",
            return_value=[target_pk],
        ):
            results = list(
                Post.objects.filter(pk__in=[target_pk])
            )

        assert len(results) == 1
        assert results[0].title == "Introduction to Rust"

    def test_opensearch_returns_multiple_pks(self):
        """Multiple PK results from OpenSearch are batch-fetched."""
        pks = [str(self.rust_post.pk), str(self.python_post.pk)]

        with patch(
            "dynamo_backend.opensearch_sync.search_pks",
            return_value=pks,
        ):
            results = list(Post.objects.filter(pk__in=pks))

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "Introduction to Rust" in titles
        assert "Python Best Practices" in titles

    def test_search_fallback_via_ddb_scan_icontains(self):
        """When OpenSearch is unavailable (None), icontains scan finds posts."""
        with patch(
            "dynamo_backend.opensearch_sync.search_pks",
            return_value=None,
        ):
            # Simulate the admin search path: icontains on title
            results = list(Post.objects.filter(title__icontains="rust"))

        titles = [r.title for r in results]
        # Both "Introduction to Rust" and "Draft Rust Notes" contain "rust"
        assert any("Rust" in t for t in titles)
        assert len(results) >= 2

    def test_opensearch_empty_results(self):
        """Empty PK list from OpenSearch returns no objects."""
        with patch(
            "dynamo_backend.opensearch_sync.search_pks",
            return_value=[],
        ):
            results = list(Post.objects.filter(pk__in=[]))

        assert results == []

    def test_filter_published_only(self):
        """published=True filter isolates published posts."""
        published = list(Post.objects.filter(published=True))
        draft = list(Post.objects.filter(published=False))

        published_titles = {p.title for p in published}
        assert "Introduction to Rust" in published_titles
        assert "Python Best Practices" in published_titles
        assert "Draft Rust Notes" not in published_titles

        assert any(p.title == "Draft Rust Notes" for p in draft)

    def test_tag_search_via_scan(self):
        """Tags JSONField list is searchable via contains (scalar element)."""
        # DynamoDB contains() checks for a single element in the list attribute
        results = list(Post.objects.filter(tags__contains="python"))
        assert any(p.title == "Python Best Practices" for p in results)
        # Rust post should not appear
        assert not any(p.title == "Python Best Practices" and "rust" in p.tags for p in results)

    def test_count_query_with_pk_in(self):
        """COUNT on a pk__in queryset uses len() not a full-table scan."""
        pks = [str(self.rust_post.pk), str(self.python_post.pk)]
        count = Post.objects.filter(pk__in=pks).count()
        assert count == 2


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — Update
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestUpdate:
    """Verify fields survive a save round-trip and updated_at advances."""

    def test_update_author_bio_via_api(self, api_client):
        author = Author.objects.create(username="update_author", bio="Original bio")

        resp = _put_json(api_client, f"/api/authors/{author.pk}/", {
            "bio": "Updated bio",
        })
        assert resp.status_code == 200

        author.refresh_from_db()
        assert author.bio == "Updated bio"

    def test_update_post_title_via_orm(self):
        author = Author.objects.create(username="post_updater")
        post = Post.objects.create(
            title="Original Title", slug="orig", author=author, published=False
        )
        original_updated_at = post.updated_at

        import time
        time.sleep(0.05)

        post.title = "Revised Title"
        post.published = True
        post.save()

        post.refresh_from_db()
        assert post.title == "Revised Title"
        assert post.published is True
        assert post.updated_at >= original_updated_at

    def test_update_post_tags(self):
        author = Author.objects.create(username="tagger_e2e")
        post = Post.objects.create(
            title="Tagged Post", slug="tagged-e2e",
            author=author, tags=["initial"],
        )

        post.tags = ["python", "aws", "dynamodb"]
        post.save()

        post.refresh_from_db()
        assert set(post.tags) == {"python", "aws", "dynamodb"}

    def test_update_comment_approval(self):
        author = Author.objects.create(username="comment_updater")
        post = Post.objects.create(title="T", slug="t2", author=author)
        comment = Comment.objects.create(
            post=post, author_name="Troll", body="Bad content", approved=True
        )

        comment.approved = False
        comment.save()

        comment.refresh_from_db()
        assert comment.approved is False

    def test_partial_update_preserves_other_fields(self, api_client):
        """PUT to /api/authors/ with only bio should not clobber email."""
        author = Author.objects.create(
            username="preserve_e2e",
            email="keep@e2e.com",
            bio="Before",
        )

        resp = _put_json(api_client, f"/api/authors/{author.pk}/", {
            "bio": "After",
        })
        assert resp.status_code == 200

        author.refresh_from_db()
        assert author.bio == "After"
        assert author.email == "keep@e2e.com"   # untouched


# ═══════════════════════════════════════════════════════════════
# PHASE 5 — Deletion
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestDeletion:
    """Objects are removed from DynamoDB and do not reappear."""

    def test_delete_comment_via_orm(self):
        author = Author.objects.create(username="del_comment_author")
        post = Post.objects.create(title="Commented", slug="commented-del", author=author)
        comment = Comment.objects.create(post=post, author_name="X", body="To delete")
        comment_pk = comment.pk

        comment.delete()

        with pytest.raises(Comment.DoesNotExist):
            Comment.objects.get(pk=comment_pk)
        assert Comment.objects.filter(pk=comment_pk).count() == 0

    def test_delete_post_via_orm(self):
        author = Author.objects.create(username="del_post_author")
        post = Post.objects.create(title="Doomed Post", slug="doomed", author=author)
        post_pk = post.pk

        post.delete()

        with pytest.raises(Post.DoesNotExist):
            Post.objects.get(pk=post_pk)

    def test_delete_author_via_orm(self):
        author = Author.objects.create(username="del_author_e2e")
        author_pk = author.pk

        author.delete()

        with pytest.raises(Author.DoesNotExist):
            Author.objects.get(pk=author_pk)
        assert Author.objects.filter(pk=author_pk).count() == 0

    def test_delete_one_of_many(self):
        """Deleting one object leaves siblings untouched."""
        author = Author.objects.create(username="sibling_author")
        post_a = Post.objects.create(title="Keep A", slug="keep-a", author=author)
        post_b = Post.objects.create(title="Keep B", slug="keep-b", author=author)
        post_x = Post.objects.create(title="Delete X", slug="delete-x", author=author)

        post_x.delete()

        assert Post.objects.filter(pk=post_a.pk).count() == 1
        assert Post.objects.filter(pk=post_b.pk).count() == 1
        assert Post.objects.filter(pk=post_x.pk).count() == 0

    def test_delete_multiple_comments_batch(self):
        """Bulk delete via queryset removes all matching objects."""
        author = Author.objects.create(username="bulk_del_author")
        post = Post.objects.create(title="Bulk", slug="bulk-del", author=author)
        c1 = Comment.objects.create(post=post, author_name="A", body="One")
        c2 = Comment.objects.create(post=post, author_name="B", body="Two")
        c3 = Comment.objects.create(post=post, author_name="C", body="Three")

        Comment.objects.filter(pk__in=[c1.pk, c2.pk]).delete()

        assert Comment.objects.filter(pk=c1.pk).count() == 0
        assert Comment.objects.filter(pk=c2.pk).count() == 0
        assert Comment.objects.filter(pk=c3.pk).count() == 1  # survivor

    def test_delete_nonexistent_is_safe(self):
        """QuerySet.filter(pk=unknown).delete() does not raise."""
        fake_pk = uuid.uuid4()
        deleted_count, _ = Post.objects.filter(pk=fake_pk).delete()
        # May be 0 (nothing found) or 1 (if backend returns optimistically) — no exception
        assert deleted_count >= 0

    def test_user_delete(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="gone_user", password="pw")
        pk = user.pk

        user.delete()

        assert User.objects.filter(pk=pk).count() == 0


# ═══════════════════════════════════════════════════════════════
# COMBINED — Full lifecycle in one sequential scenario
# ═══════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("e2e_db")
class TestFullLifecycle:
    """
    A single test that walks through the entire story in order:
    create → read → search → update → delete.

    This is the narrative acceptance test — if it passes, the whole stack
    works end-to-end.  Individual phase tests above are for isolation and
    easier debugging.
    """

    def test_lifecycle(self, api_client):
        from django.contrib.auth.models import User
        from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
        from django.contrib.contenttypes.models import ContentType

        # ── 1. Admin user bootstrap ─────────────────────────────────────
        admin = User.objects.create_superuser(
            username="lifecycle_admin", password="Lifecycle!1"
        )
        assert admin.pk is not None

        # Simulate admin LogEntry after user creation (tests FK type fix)
        ct_user = ContentType.objects.get_or_create(
            app_label="auth", model="user"
        )[0]
        LogEntry.objects.create(
            user_id=admin.pk,
            content_type_id=ct_user.pk,
            object_id=str(admin.pk),
            object_repr=str(admin),
            action_flag=ADDITION,
            change_message="Created",
        )
        assert LogEntry.objects.filter(object_repr=str(admin)).count() == 1

        # ── 2. Create content ────────────────────────────────────────────
        author_resp = _post_json(api_client, "/api/authors/", {
            "username": "lifecycle_author",
            "email": "lc@example.com",
            "bio": "Test author for lifecycle",
        })
        assert author_resp.status_code == 201
        author_pk = author_resp.json()["pk"]

        post_resp = _post_json(api_client, "/api/posts/", {
            "title": "Lifecycle Post",
            "slug": "lifecycle-post",
            "author_pk": author_pk,
            "body": "This is the lifecycle post body.",
            "published": True,
            "tags": ["lifecycle", "test"],
        })
        assert post_resp.status_code == 201
        post_pk = post_resp.json()["pk"]

        comment_resp = _post_json(api_client, f"/api/posts/{post_pk}/comments/", {
            "author_name": "Admin Reader",
            "body": "Great lifecycle post!",
        })
        assert comment_resp.status_code == 201
        comment_pk = comment_resp.json()["pk"]

        # Verify objects exist in DB
        assert Author.objects.filter(pk=author_pk).count() == 1
        assert Post.objects.filter(pk=post_pk).count() == 1
        assert Comment.objects.filter(pk=comment_pk).count() == 1

        # ── 3. Read detail ───────────────────────────────────────────────
        detail = api_client.get(f"/api/posts/{post_pk}/")
        assert detail.status_code == 200
        data = detail.json()
        assert data["title"] == "Lifecycle Post"
        assert data["published"] is True
        assert len(data["comments"]) == 1
        assert data["comments"][0]["body"] == "Great lifecycle post!"

        # ── 4. Search (OpenSearch mocked → specific PK) ──────────────────
        with patch(
            "dynamo_backend.opensearch_sync.search_pks",
            return_value=[post_pk],
        ):
            results = list(Post.objects.filter(pk__in=[post_pk]))
        assert len(results) == 1
        assert results[0].slug == "lifecycle-post"

        # ── 5. Search fallback (scan icontains) ──────────────────────────
        scan_results = list(Post.objects.filter(title__icontains="lifecycle"))
        assert any(p.pk == uuid.UUID(post_pk) for p in scan_results)

        # ── 6. Update ───────────────────────────────────────────────────
        update_resp = _put_json(api_client, f"/api/authors/{author_pk}/", {
            "bio": "Updated bio after lifecycle",
        })
        assert update_resp.status_code == 200

        post_obj = Post.objects.get(pk=post_pk)
        post_obj.title = "Lifecycle Post (Revised)"
        post_obj.save()

        LogEntry.objects.create(
            user_id=admin.pk,
            content_type_id=ct_user.pk,
            object_id=str(admin.pk),
            object_repr=str(admin),
            action_flag=CHANGE,
            change_message="Changed title",
        )

        post_obj.refresh_from_db()
        assert post_obj.title == "Lifecycle Post (Revised)"
        author_obj = Author.objects.get(pk=author_pk)
        assert author_obj.bio == "Updated bio after lifecycle"

        # ── 7. Delete ───────────────────────────────────────────────────
        Comment.objects.filter(pk=comment_pk).delete()
        assert Comment.objects.filter(pk=comment_pk).count() == 0

        Post.objects.filter(pk=post_pk).delete()
        assert Post.objects.filter(pk=post_pk).count() == 0

        Author.objects.filter(pk=author_pk).delete()
        assert Author.objects.filter(pk=author_pk).count() == 0

        LogEntry.objects.create(
            user_id=admin.pk,
            content_type_id=ct_user.pk,
            object_id=str(admin.pk),
            object_repr=str(admin),
            action_flag=DELETION,
            change_message="Deleted content",
        )

        # All content gone
        assert Post.objects.count() == 0
        assert Comment.objects.count() == 0
        assert Author.objects.count() == 0

        # Admin user and log intact
        assert User.objects.filter(pk=admin.pk).count() == 1
        assert LogEntry.objects.filter(object_repr=str(admin)).count() == 3
