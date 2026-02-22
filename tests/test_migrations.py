"""
tests/test_migrations.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the dynamo_backend migration system.

Covers:
  - migration_fields  (serialization round-trips)
  - migration_ops     (state mutation + DynamoDB apply)
  - migration_recorder (history table CRUD)
  - migration_loader  (file discovery, ordering, state replay)
  - migration_autodetector (change detection)
  - migration_writer  (file generation)
  - migration_executor (end-to-end run)
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import textwrap
from typing import Dict, List, Tuple
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────── fixtures

@pytest.fixture(autouse=True)
def dynamo_mock(mock_dynamodb):
    """All migration tests get a fresh moto DynamoDB."""
    yield


# ═══════════════════════════════════════════════════════════════════
#  migration_fields
# ═══════════════════════════════════════════════════════════════════

class TestMigrationFields:
    def test_charfield_roundtrip(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import field_to_dict, dict_to_field

        f = CharField(max_length=100, nullable=False, default="hello")
        d = field_to_dict(f)
        assert d["type"] == "CharField"
        assert d["max_length"] == 100
        assert d["nullable"] is False
        assert d["default"] == "hello"

        f2 = dict_to_field(d)
        assert isinstance(f2, CharField)
        assert f2.max_length == 100
        assert f2.nullable is False

    def test_booleanfield_roundtrip(self):
        from dynamo_backend.fields import BooleanField
        from dynamo_backend.migration_fields import field_to_dict, dict_to_field

        f = BooleanField(default=True)
        d = field_to_dict(f)
        assert d["type"] == "BooleanField"
        f2 = dict_to_field(d)
        assert isinstance(f2, BooleanField)
        assert f2._default is True

    def test_integerfield_roundtrip(self):
        from dynamo_backend.fields import IntegerField
        from dynamo_backend.migration_fields import field_to_dict, dict_to_field

        f = IntegerField(default=0)
        d = field_to_dict(f)
        f2 = dict_to_field(d)
        assert f2._default == 0

    def test_jsonfield_roundtrip(self):
        from dynamo_backend.fields import JSONField
        from dynamo_backend.migration_fields import field_to_dict, dict_to_field

        f = JSONField(default=dict)
        d = field_to_dict(f)
        # callable default stored as None
        f2 = dict_to_field(d)
        assert isinstance(f2, JSONField)

    def test_fields_equal_same(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import fields_equal

        f1 = CharField(max_length=50)
        f2 = CharField(max_length=50)
        assert fields_equal(f1, f2)

    def test_fields_equal_different(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import fields_equal

        f1 = CharField(max_length=50)
        f2 = CharField(max_length=100)
        assert not fields_equal(f1, f2)

    def test_unknown_type_raises(self):
        from dynamo_backend.migration_fields import dict_to_field

        with pytest.raises(ValueError, match="Unknown field type"):
            dict_to_field({"type": "NonExistentField"})


# ═══════════════════════════════════════════════════════════════════
#  migration_ops — state
# ═══════════════════════════════════════════════════════════════════

class TestMigrationOpsState:
    def _empty_state(self) -> Dict:
        return {}

    def test_create_table_apply_to_state(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable

        op = CreateTable(
            app_label="myapp",
            model_name="MyModel",
            table_name="myapp_mymodel",
            fields=[("title", CharField(max_length=100))],
        )
        state: Dict = {}
        op.apply_to_state(state)
        assert "myapp.MyModel" in state
        assert state["myapp.MyModel"]["table_name"] == "myapp_mymodel"
        assert "title" in state["myapp.MyModel"]["fields"]

    def test_add_field_apply_to_state(self):
        from dynamo_backend.fields import BooleanField, CharField
        from dynamo_backend.migration_ops import CreateTable, AddField

        state: Dict = {}
        CreateTable("app", "M", "app_m", [("name", CharField())]).apply_to_state(state)
        AddField("app", "M", "active", BooleanField(default=True)).apply_to_state(state)
        assert "active" in state["app.M"]["fields"]

    def test_remove_field_apply_to_state(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable, RemoveField

        state: Dict = {}
        CreateTable("app", "M", "app_m", [("name", CharField())]).apply_to_state(state)
        RemoveField("app", "M", "name").apply_to_state(state)
        assert "name" not in state["app.M"]["fields"]

    def test_alter_field_apply_to_state(self):
        from dynamo_backend.fields import CharField, IntegerField
        from dynamo_backend.migration_ops import CreateTable, AlterField

        state: Dict = {}
        CreateTable("app", "M", "app_m", [("score", CharField())]).apply_to_state(state)
        AlterField("app", "M", "score", IntegerField(default=0)).apply_to_state(state)
        assert state["app.M"]["fields"]["score"]["type"] == "IntegerField"

    def test_add_index_apply_to_state(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable, AddIndex

        state: Dict = {}
        CreateTable("app", "M", "app_m", [("slug", CharField())]).apply_to_state(state)
        AddIndex("app", "M", "slug").apply_to_state(state)
        assert state["app.M"]["fields"]["slug"].get("index") is True

    def test_remove_index_apply_to_state(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable, AddIndex, RemoveIndex

        state: Dict = {}
        CreateTable("app", "M", "app_m", [("slug", CharField(index=True))]).apply_to_state(state)
        AddIndex("app", "M", "slug").apply_to_state(state)
        RemoveIndex("app", "M", "slug").apply_to_state(state)
        assert state["app.M"]["fields"]["slug"].get("index") is False


# ═══════════════════════════════════════════════════════════════════
#  migration_ops — DynamoDB apply
# ═══════════════════════════════════════════════════════════════════

class TestMigrationOpsDB:
    def test_create_table_creates_dynamodb_table(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable
        from dynamo_backend.connection import get_client

        state: Dict = {}
        op = CreateTable("app", "Thing", "app_thing", [("name", CharField())])
        op.apply_to_state(state)
        op.apply_to_db(state)

        client = get_client()
        resp = client.describe_table(TableName="app_thing")
        assert resp["Table"]["TableStatus"] == "ACTIVE"

    def test_create_table_idempotent(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable

        state: Dict = {}
        op = CreateTable("app", "Thing", "app_thing2", [("name", CharField())])
        op.apply_to_state(state)
        op.apply_to_db(state)
        # Should not raise on second call
        op.apply_to_db(state)

    def test_add_field_backfills_existing_items(self):
        """AddField.apply_to_db should set the default value on existing items."""
        from dynamo_backend.fields import CharField, BooleanField
        from dynamo_backend.migration_ops import CreateTable, AddField
        from dynamo_backend.connection import get_resource

        state: Dict = {}
        CreateTable(
            "bl", "Article", "bl_article", [("title", CharField())]
        ).apply_to_state(state)
        CreateTable(
            "bl", "Article", "bl_article",
            [("title", CharField())],
        ).apply_to_db(state)

        # Insert items without the new field
        table = get_resource().Table("bl_article")
        table.put_item(Item={"pk": "1", "title": "First"})
        table.put_item(Item={"pk": "2", "title": "Second"})

        # Apply AddField with a default
        op = AddField("bl", "Article", "published", BooleanField(default=False))
        op.apply_to_state(state)
        op.apply_to_db(state)

        # Both items should now have 'published' = False
        for pk in ("1", "2"):
            item = table.get_item(Key={"pk": pk})["Item"]
            assert item.get("published") is False

    def test_add_field_no_default_skips_backfill(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable, AddField
        from dynamo_backend.connection import get_resource

        state: Dict = {}
        CreateTable("bl", "Widget", "bl_widget", []).apply_to_state(state)
        CreateTable("bl", "Widget", "bl_widget", []).apply_to_db(state)

        table = get_resource().Table("bl_widget")
        table.put_item(Item={"pk": "1"})

        # nullable + no default → nothing to backfill
        op = AddField("bl", "Widget", "notes", CharField(nullable=True))
        op.apply_to_state(state)
        op.apply_to_db(state)   # should not raise

        item = table.get_item(Key={"pk": "1"})["Item"]
        assert "notes" not in item

    def test_remove_field_is_noop_on_db(self):
        """RemoveField never touches DynamoDB (it's schemaless)."""
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable, RemoveField

        state: Dict = {}
        CreateTable("bl", "X", "bl_x", [("tag", CharField())]).apply_to_state(state)
        CreateTable("bl", "X", "bl_x", [("tag", CharField())]).apply_to_db(state)
        RemoveField("bl", "X", "tag").apply_to_state(state)
        RemoveField("bl", "X", "tag").apply_to_db(state)   # must not raise


# ═══════════════════════════════════════════════════════════════════
#  migration_recorder
# ═══════════════════════════════════════════════════════════════════

class TestMigrationRecorder:
    def test_ensure_history_table_creates_table(self):
        from dynamo_backend.migration_recorder import MigrationRecorder
        from dynamo_backend.connection import get_client

        r = MigrationRecorder()
        r.ensure_history_table()
        client = get_client()
        resp = client.describe_table(TableName="_dynamo_migration_history")
        assert resp["Table"]["TableStatus"] == "ACTIVE"

    def test_record_and_query_applied(self):
        from dynamo_backend.migration_recorder import MigrationRecorder

        r = MigrationRecorder()
        r.ensure_history_table()
        assert ("demo_app", "0001_initial") not in r.applied_migrations()
        r.record_applied("demo_app", "0001_initial")
        assert ("demo_app", "0001_initial") in r.applied_migrations()

    def test_record_unapplied(self):
        from dynamo_backend.migration_recorder import MigrationRecorder

        r = MigrationRecorder()
        r.ensure_history_table()
        r.record_applied("demo_app", "0001_initial")
        r.record_unapplied("demo_app", "0001_initial")
        assert ("demo_app", "0001_initial") not in r.applied_migrations()

    def test_multiple_apps_independent(self):
        from dynamo_backend.migration_recorder import MigrationRecorder

        r = MigrationRecorder()
        r.ensure_history_table()
        r.record_applied("app_a", "0001_initial")
        r.record_applied("app_b", "0001_initial")
        applied = r.applied_migrations()
        assert ("app_a", "0001_initial") in applied
        assert ("app_b", "0001_initial") in applied


# ═══════════════════════════════════════════════════════════════════
#  migration_autodetector
# ═══════════════════════════════════════════════════════════════════

class TestMigrationAutodetector:
    def _state_with_model(self, key, table, fields_dict):
        return {key: {"table_name": table, "fields": fields_dict}}

    def test_detect_new_model(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import field_to_dict
        from dynamo_backend.migration_ops import CreateTable

        live = {
            "myapp.Post": {
                "table_name": "myapp_post",
                "fields": {"title": field_to_dict(CharField(max_length=200))},
            }
        }
        ops = detect_changes({}, live, "myapp")
        assert len(ops) == 1
        assert isinstance(ops[0], CreateTable)
        assert ops[0].model_name == "Post"

    def test_detect_new_field(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField, BooleanField
        from dynamo_backend.migration_fields import field_to_dict
        from dynamo_backend.migration_ops import AddField

        base_fields = {"title": field_to_dict(CharField(max_length=200))}
        mig_state = {"myapp.Post": {"table_name": "myapp_post", "fields": base_fields}}
        live_state = {
            "myapp.Post": {
                "table_name": "myapp_post",
                "fields": {
                    **base_fields,
                    "public": field_to_dict(BooleanField(default=True)),
                },
            }
        }
        ops = detect_changes(mig_state, live_state, "myapp")
        add_ops = [o for o in ops if isinstance(o, AddField)]
        assert len(add_ops) == 1
        assert add_ops[0].field_name == "public"

    def test_detect_removed_field(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField, BooleanField
        from dynamo_backend.migration_fields import field_to_dict
        from dynamo_backend.migration_ops import RemoveField

        base_fields = {
            "title": field_to_dict(CharField(max_length=200)),
            "legacy": field_to_dict(CharField(nullable=True)),
        }
        mig_state = {"myapp.Post": {"table_name": "myapp_post", "fields": base_fields}}
        live_state = {
            "myapp.Post": {
                "table_name": "myapp_post",
                "fields": {"title": field_to_dict(CharField(max_length=200))},
            }
        }
        ops = detect_changes(mig_state, live_state, "myapp")
        rm_ops = [o for o in ops if isinstance(o, RemoveField)]
        assert len(rm_ops) == 1
        assert rm_ops[0].field_name == "legacy"

    def test_detect_new_index(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import field_to_dict
        from dynamo_backend.migration_ops import AddIndex

        mig_state = {
            "myapp.Tag": {
                "table_name": "myapp_tag",
                "fields": {"slug": field_to_dict(CharField(max_length=50))},
            }
        }
        live_state = {
            "myapp.Tag": {
                "table_name": "myapp_tag",
                "fields": {"slug": field_to_dict(CharField(max_length=50, index=True))},
            }
        }
        ops = detect_changes(mig_state, live_state, "myapp")
        idx_ops = [o for o in ops if isinstance(o, AddIndex)]
        assert len(idx_ops) == 1
        assert idx_ops[0].field_name == "slug"

    def test_no_changes(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import field_to_dict

        fields = {"title": field_to_dict(CharField(max_length=200))}
        state = {"myapp.Post": {"table_name": "myapp_post", "fields": fields}}
        ops = detect_changes(state, state, "myapp")
        assert ops == []

    def test_different_app_label_ignored(self):
        from dynamo_backend.migration_autodetector import detect_changes
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_fields import field_to_dict
        from dynamo_backend.migration_ops import CreateTable

        live = {
            "other_app.Thing": {
                "table_name": "other_app_thing",
                "fields": {"x": field_to_dict(CharField())},
            }
        }
        ops = detect_changes({}, live, "myapp")
        assert ops == []


# ═══════════════════════════════════════════════════════════════════
#  migration_writer
# ═══════════════════════════════════════════════════════════════════

class TestMigrationWriter:
    def test_as_string_create_table(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable
        from dynamo_backend.migration_writer import MigrationWriter

        op = CreateTable("myapp", "Post", "myapp_post", [("title", CharField(max_length=200))])
        writer = MigrationWriter(
            app_label="myapp",
            migration_name="0001_initial",
            operations=[op],
            dependencies=[],
        )
        src = writer.as_string()
        assert "class Migration:" in src
        assert "CreateTable" in src
        assert "myapp_post" in src
        assert "dependencies = []" in src

    def test_as_string_with_dependencies(self):
        from dynamo_backend.fields import BooleanField
        from dynamo_backend.migration_ops import AddField
        from dynamo_backend.migration_writer import MigrationWriter

        op = AddField("myapp", "Post", "active", BooleanField(default=True))
        writer = MigrationWriter(
            app_label="myapp",
            migration_name="0002_post_active",
            operations=[op],
            dependencies=[("myapp", "0001_initial")],
        )
        src = writer.as_string()
        assert "0001_initial" in src
        assert "AddField" in src
        assert "active" in src

    def test_write_creates_file(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable
        from dynamo_backend.migration_writer import MigrationWriter

        op = CreateTable("myapp", "Post", "myapp_post", [("title", CharField())])
        writer = MigrationWriter("myapp", "0001_initial", [op], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = writer.write(tmpdir)
            assert os.path.isfile(path)
            assert path.endswith("0001_initial.py")
            init_path = os.path.join(tmpdir, "dynamo_migrations", "__init__.py")
            assert os.path.isfile(init_path)
            content = open(path).read()
            assert "CreateTable" in content

    def test_written_file_is_importable(self):
        from dynamo_backend.fields import CharField
        from dynamo_backend.migration_ops import CreateTable
        from dynamo_backend.migration_writer import MigrationWriter

        op = CreateTable("myapp", "Post", "myapp_post", [("title", CharField())])
        writer = MigrationWriter("myapp", "0001_initial", [op], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = writer.write(tmpdir)
            # Dynamically import the written file
            spec = importlib.util.spec_from_file_location("test_mig_0001", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            assert hasattr(mod, "Migration")
            assert isinstance(mod.Migration.operations, list)
            assert len(mod.Migration.operations) == 1


# ═══════════════════════════════════════════════════════════════════
#  migration_executor  (end-to-end with temp migration files)
# ═══════════════════════════════════════════════════════════════════

class TestMigrationExecutor:
    """
    Build a fake app with two real migration files in a temp directory,
    point the loader at them, and verify the executor applies them correctly.
    """

    def _write_migration(self, mig_dir: str, filename: str, content: str) -> None:
        os.makedirs(mig_dir, exist_ok=True)
        init = os.path.join(mig_dir, "__init__.py")
        if not os.path.exists(init):
            open(init, "w").close()
        with open(os.path.join(mig_dir, filename), "w") as f:
            f.write(content)

    def test_migrate_applies_pending(self):
        from dynamo_backend.migration_loader import MigrationLoader
        from dynamo_backend.migration_recorder import MigrationRecorder
        from dynamo_backend.migration_executor import MigrationExecutor
        from dynamo_backend.connection import get_client

        with tempfile.TemporaryDirectory() as tmpdir:
            mig_dir = os.path.join(tmpdir, "dynamo_migrations")
            mig0001 = textwrap.dedent("""\
                from dynamo_backend import migration_ops as migrations
                from dynamo_backend import fields

                class Migration:
                    dependencies = []
                    operations = [
                        migrations.CreateTable(
                            app_label='fakeapp',
                            model_name='Widget',
                            table_name='fakeapp_widget',
                            fields=[('name', fields.CharField(max_length=100))],
                        ),
                    ]
            """)
            self._write_migration(mig_dir, "0001_initial.py", mig0001)

            # Patch the loader to use our temp directory
            with _patch_loader_for_app("fakeapp", tmpdir, mig_dir):
                recorder = MigrationRecorder()
                recorder.ensure_history_table()

                executor = MigrationExecutor(verbosity=0)
                executor.loader = MigrationLoader()
                executor.recorder = recorder
                executor.migrate(app_label="fakeapp")

                # Table should be created
                client = get_client()
                resp = client.describe_table(TableName="fakeapp_widget")
                assert resp["Table"]["TableStatus"] == "ACTIVE"

                # Migration should be recorded
                applied = recorder.applied_migrations()
                assert ("fakeapp", "0001_initial") in applied

    def test_migrate_is_idempotent(self):
        from dynamo_backend.migration_loader import MigrationLoader
        from dynamo_backend.migration_recorder import MigrationRecorder
        from dynamo_backend.migration_executor import MigrationExecutor

        with tempfile.TemporaryDirectory() as tmpdir:
            mig_dir = os.path.join(tmpdir, "dynamo_migrations")
            mig0001 = textwrap.dedent("""\
                from dynamo_backend import migration_ops as migrations
                from dynamo_backend import fields

                class Migration:
                    dependencies = []
                    operations = [
                        migrations.CreateTable(
                            app_label='fakeapp2',
                            model_name='Widget',
                            table_name='fakeapp2_widget',
                            fields=[],
                        ),
                    ]
            """)
            self._write_migration(mig_dir, "0001_initial.py", mig0001)

            with _patch_loader_for_app("fakeapp2", tmpdir, mig_dir):
                recorder = MigrationRecorder()
                recorder.ensure_history_table()

                for _ in range(2):   # run twice
                    executor = MigrationExecutor(verbosity=0)
                    executor.loader = MigrationLoader()
                    executor.recorder = recorder
                    executor.migrate(app_label="fakeapp2")

                applied = recorder.applied_migrations()
                # Should still only be recorded once
                recorded = [k for k in applied if k[0] == "fakeapp2"]
                assert len(recorded) == 1

    def test_migration_status_shows_applied_flag(self):
        from dynamo_backend.migration_loader import MigrationLoader
        from dynamo_backend.migration_recorder import MigrationRecorder
        from dynamo_backend.migration_executor import MigrationExecutor

        with tempfile.TemporaryDirectory() as tmpdir:
            mig_dir = os.path.join(tmpdir, "dynamo_migrations")
            mig0001 = textwrap.dedent("""\
                from dynamo_backend import migration_ops as migrations
                from dynamo_backend import fields

                class Migration:
                    dependencies = []
                    operations = [
                        migrations.CreateTable(
                            app_label='fakeapp3',
                            model_name='X',
                            table_name='fakeapp3_x',
                            fields=[],
                        ),
                    ]
            """)
            self._write_migration(mig_dir, "0001_initial.py", mig0001)

            with _patch_loader_for_app("fakeapp3", tmpdir, mig_dir):
                recorder = MigrationRecorder()
                recorder.ensure_history_table()

                executor = MigrationExecutor(verbosity=0)
                executor.loader = MigrationLoader()
                executor.recorder = recorder

                status_before = executor.migration_status()
                assert any(
                    app == "fakeapp3" and name == "0001_initial" and not applied
                    for app, name, applied in status_before
                )

                executor.migrate(app_label="fakeapp3")

                executor2 = MigrationExecutor(verbosity=0)
                executor2.loader = MigrationLoader()
                executor2.recorder = recorder
                status_after = executor2.migration_status()
                assert any(
                    app == "fakeapp3" and name == "0001_initial" and applied
                    for app, name, applied in status_after
                )


# ─────────────────────────────────────────────────── helpers

def _patch_loader_for_app(app_label: str, app_path: str, mig_dir: str):
    """
    Context manager that injects a fake Django app config and a fake Python
    package for *app_label* so MigrationLoader can discover migrations from
    *mig_dir* without needing a real installed Django app.
    """
    from unittest.mock import MagicMock, patch
    import types

    # Create a fake module for the dynamo_migrations sub-package
    pkg_name = f"{app_label}.dynamo_migrations"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [mig_dir]
    pkg_mod.__package__ = pkg_name

    app_mod = types.ModuleType(app_label)
    app_mod.__path__ = [app_path]

    fake_config = MagicMock()
    fake_config.label = app_label
    fake_config.name = app_label
    fake_config.path = app_path

    original_modules = dict(sys.modules)

    def enter():
        sys.modules[app_label] = app_mod
        sys.modules[pkg_name] = pkg_mod
        return fake_config

    def exit_ctx():
        # Remove only the modules we added
        for k in list(sys.modules.keys()):
            if k.startswith(app_label + ".dynamo_migrations") or k == app_label:
                sys.modules.pop(k, None)

    class CM:
        def __enter__(self):
            enter()
            self._patch = patch(
                "django.apps.apps.get_app_configs",
                return_value=[fake_config],
            )
            self._patch.start()
            return self

        def __exit__(self, *_):
            self._patch.stop()
            exit_ctx()

    return CM()
