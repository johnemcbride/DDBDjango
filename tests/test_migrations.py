"""
tests/test_migrations.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the DynamoDB SchemaEditor's field-level migration behaviour.

DynamoDB is schemaless — there is no DDL for add/remove/alter columns. What
*does* matter is the data contract:

  add_field  (non-null + default) → backfill existing items with the default
  add_field  (nullable)           → no-op is fine
  alter_field (null → non-null)   → backfill items that have no value
  rename_field                    → copy attribute under new name, drop old one
  remove_field                    → leave existing attributes; Django ignores them

These tests wire up a real SchemaEditor against a moto-mocked DynamoDB table,
insert a few items *without* the new attribute present, run the migration
operation, and then verify the items were updated correctly.
"""

from __future__ import annotations

import uuid
import pytest

from django.db import models as dj_models, connection


# ── helpers ───────────────────────────────────────────────────────────────────

def _put_raw(table, pk_name: str, **attrs):
    """Write an item without the fields added by later migrations."""
    table.put_item(Item={pk_name: str(uuid.uuid4()), **attrs})


def _all_items(table) -> list[dict]:
    resp = table.scan()
    return resp.get("Items", [])


def _schema_editor():
    return connection.schema_editor()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def author_table(mock_dynamodb):
    """Return the live moto Author table (tables created by mock_dynamodb)."""
    from demo_app.models import Author
    from dynamo_backend.backends.dynamodb.base import get_dynamodb_resource
    dynamodb = get_dynamodb_resource(connection)
    return dynamodb.Table(Author._meta.db_table)


@pytest.fixture()
def post_table(mock_dynamodb):
    from demo_app.models import Post
    from dynamo_backend.backends.dynamodb.base import get_dynamodb_resource
    dynamodb = get_dynamodb_resource(connection)
    return dynamodb.Table(Post._meta.db_table)


# ── add_field — non-null with default ─────────────────────────────────────────

class TestAddFieldNonNull:
    """Adding a non-null field with a default should backfill all existing items."""

    def test_string_field_backfilled(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        # Write two legacy items that have no 'nickname' attribute
        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="alice")
        _put_raw(author_table, pk_name, username="bob")

        # Simulate adding: nickname = CharField(max_length=50, default="anon")
        field = dj_models.CharField(max_length=50, default="anon")
        field.set_attributes_from_name("nickname")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        # All items should now have nickname == "anon"
        items = _all_items(author_table)
        assert len(items) == 2
        for item in items:
            assert item.get("nickname") == "anon", f"Expected 'anon' but got {item}"

    def test_integer_field_backfilled(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="charlie")

        field = dj_models.IntegerField(default=42)
        field.set_attributes_from_name("score")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        items = _all_items(author_table)
        assert len(items) == 1
        import decimal
        assert items[0].get("score") in (42, decimal.Decimal("42"))

    def test_boolean_field_backfilled(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="dana")

        field = dj_models.BooleanField(default=True)
        field.set_attributes_from_name("is_active")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        items = _all_items(author_table)
        assert items[0].get("is_active") is True

    def test_json_field_backfilled(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="eve")

        field = dj_models.JSONField(default=list)
        field.set_attributes_from_name("interests")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        items = _all_items(author_table)
        assert items[0].get("interests") == []

    def test_already_set_items_not_overwritten(self, author_table, mock_dynamodb):
        """Items that already have the attribute must not be changed."""
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        # legacy item (no attribute)
        _put_raw(author_table, pk_name, username="frank")
        # modern item (already has the attribute set to a non-default value)
        _put_raw(author_table, pk_name, username="grace", score="99")

        field = dj_models.CharField(max_length=10, default="0")
        field.set_attributes_from_name("score")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        items = {i["username"]: i for i in _all_items(author_table)}
        assert items["frank"]["score"] == "0"    # backfilled
        assert items["grace"]["score"] == "99"   # not overwritten

    def test_empty_table_is_noop(self, author_table, mock_dynamodb):
        """A brand-new table has no items to backfill — should not raise."""
        from demo_app.models import Author

        field = dj_models.CharField(max_length=50, default="default_val")
        field.set_attributes_from_name("extra")
        field.null = False

        with _schema_editor() as editor:
            editor.add_field(Author, field)  # should not raise

        assert _all_items(author_table) == []


# ── add_field — nullable (no-op) ──────────────────────────────────────────────

class TestAddFieldNullable:
    """Adding a nullable field should be a no-op — attributes must not appear."""

    def test_nullable_field_no_backfill(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="helga")

        field = dj_models.CharField(max_length=50, null=True, blank=True, default=None)
        field.set_attributes_from_name("middle_name")

        with _schema_editor() as editor:
            editor.add_field(Author, field)

        items = _all_items(author_table)
        assert "middle_name" not in items[0]


# ── alter_field — null → non-null ─────────────────────────────────────────────

class TestAlterFieldNullToNonNull:
    """Promoting a field from null=True to null=False should backfill."""

    def test_null_to_non_null_backfills(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        # Item written without the attribute (simulating old nullable field)
        _put_raw(author_table, pk_name, username="ivan")

        old_field = dj_models.CharField(max_length=50, null=True, blank=True)
        old_field.set_attributes_from_name("status")
        old_field.null = True

        new_field = dj_models.CharField(max_length=50, default="active")
        new_field.set_attributes_from_name("status")
        new_field.null = False

        with _schema_editor() as editor:
            editor.alter_field(Author, old_field, new_field)

        items = _all_items(author_table)
        assert items[0].get("status") == "active"

    def test_non_null_to_non_null_no_backfill(self, author_table, mock_dynamodb):
        """Changing a non-null field's default should not touch existing items."""
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="julia", score="5")

        old_field = dj_models.IntegerField(default=0)
        old_field.set_attributes_from_name("score")
        old_field.null = False

        new_field = dj_models.IntegerField(default=99)
        new_field.set_attributes_from_name("score")
        new_field.null = False

        with _schema_editor() as editor:
            editor.alter_field(Author, old_field, new_field)

        # score was already "5" — should not be touched
        items = _all_items(author_table)
        assert items[0]["score"] == "5"


# ── rename_field ──────────────────────────────────────────────────────────────

class TestRenameField:
    """rename_field should copy the value under the new name and drop the old."""

    def test_rename_copies_and_removes_old(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="karl", nickname="kk")

        old_field = dj_models.CharField(max_length=50)
        old_field.set_attributes_from_name("nickname")

        new_field = dj_models.CharField(max_length=50)
        new_field.set_attributes_from_name("handle")

        with _schema_editor() as editor:
            editor.rename_field(Author, old_field, new_field)

        items = _all_items(author_table)
        assert items[0].get("handle") == "kk"
        assert "nickname" not in items[0]

    def test_rename_items_without_old_attr_are_skipped(self, author_table, mock_dynamodb):
        """Items missing the old attribute must remain untouched."""
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="leo")  # no 'nickname'

        old_field = dj_models.CharField(max_length=50)
        old_field.set_attributes_from_name("nickname")

        new_field = dj_models.CharField(max_length=50)
        new_field.set_attributes_from_name("handle")

        with _schema_editor() as editor:
            editor.rename_field(Author, old_field, new_field)  # should not raise

        items = _all_items(author_table)
        assert "handle" not in items[0]
        assert "nickname" not in items[0]

    def test_rename_noop_when_same_name(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="mia", nickname="mm")

        field = dj_models.CharField(max_length=50)
        field.set_attributes_from_name("nickname")

        with _schema_editor() as editor:
            editor.rename_field(Author, field, field)   # same → no-op

        items = _all_items(author_table)
        assert items[0].get("nickname") == "mm"


# ── remove_field ──────────────────────────────────────────────────────────────

class TestRemoveField:
    """remove_field must be a no-op — DynamoDB items keep their attributes."""

    def test_attribute_survives_remove_field(self, author_table, mock_dynamodb):
        from demo_app.models import Author

        pk_name = Author._meta.pk.attname
        _put_raw(author_table, pk_name, username="nina", legacy_col="keep_me")

        field = dj_models.CharField(max_length=50)
        field.set_attributes_from_name("legacy_col")

        with _schema_editor() as editor:
            editor.remove_field(Author, field)

        items = _all_items(author_table)
        # Data must still be there (Django will stop reading it, but it stays)
        assert items[0].get("legacy_col") == "keep_me"
