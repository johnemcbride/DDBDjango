"""
tests/test_legacy_dynamomodel.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the LEGACY dynamo_backend.legacy.DynamoModel API.

**NOTE:** This tests the deprecated DynamoModel-based approach.
For the current standard Django models approach, see test_demo_app.py

Coverage:
  - Field validation (CharField, IntegerField, BooleanField, DateTimeField,
    JSONField, UUIDField, ListField)
  - DynamoModel: create / save / delete / refresh_from_db
  - DynamoQuerySet: all / filter / exclude / get / first / count / order_by
                    / values / delete
  - Manager shortcuts: get_or_create / bulk_create
  - Error cases: DoesNotExist, MultipleObjectsReturned, ValidationError
  - Table helpers: ensure_table (idempotent), delete_table
"""

import pytest
from datetime import datetime, timezone

from dynamo_backend.exceptions import (
    DynamoObjectNotFound,
    DynamoMultipleObjectsReturned,
    DynamoValidationError,
)
from dynamo_backend.legacy.fields import (
    CharField, IntegerField, FloatField, BooleanField,
    DateTimeField, JSONField, UUIDField, ListField,
)
from dynamo_backend.legacy.models import DynamoModel
from dynamo_backend.legacy.table import ensure_table, delete_table


# ─────────────────────────────────── test model definitions

class Widget(DynamoModel):
    class Meta:
        app_label = "tests"
        table_name = "test_widgets"

    name = CharField(max_length=100, nullable=False)
    score = IntegerField(default=0)
    rating = FloatField(default=0.0)
    active = BooleanField(default=True)
    tags = ListField(default=list)
    meta = JSONField()
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


@pytest.fixture(autouse=True)
def dynamo_table(mock_dynamodb):
    """Ensure Widget table exists for every test (mock_dynamodb handles demo tables)."""
    ensure_table(Widget)
    yield
    # Table lives only within the moto context managed by mock_dynamodb


# ═══════════════════════════════════════════════════════ field tests

class TestCharField:
    def test_valid_string(self):
        f = CharField(max_length=10)
        f.name = "x"
        f.validate("hello")

    def test_exceeds_max_length(self):
        f = CharField(max_length=3)
        f.name = "x"
        with pytest.raises(DynamoValidationError):
            f.validate("toolong")

    def test_wrong_type(self):
        f = CharField(max_length=10)
        f.name = "x"
        with pytest.raises(DynamoValidationError):
            f.validate(123)

    def test_nullable_none(self):
        f = CharField(nullable=True)
        f.name = "x"
        f.validate(None)  # should not raise

    def test_non_nullable_none(self):
        f = CharField(nullable=False)
        f.name = "x"
        with pytest.raises(DynamoValidationError):
            f.validate(None)

    def test_round_trip(self):
        f = CharField()
        f.name = "x"
        assert f.from_dynamo(f.to_dynamo("hello")) == "hello"


class TestIntegerField:
    def test_valid(self):
        f = IntegerField()
        f.name = "n"
        f.validate(42)

    def test_invalid(self):
        f = IntegerField(nullable=False)
        f.name = "n"
        with pytest.raises(DynamoValidationError):
            f.validate("not_a_number")

    def test_round_trip(self):
        from decimal import Decimal
        f = IntegerField()
        f.name = "n"
        dynamo_val = f.to_dynamo(7)
        assert isinstance(dynamo_val, Decimal)
        assert f.from_dynamo(dynamo_val) == 7


class TestBooleanField:
    def test_true(self):
        f = BooleanField()
        f.name = "b"
        f.validate(True)

    def test_invalid(self):
        f = BooleanField(nullable=False)
        f.name = "b"
        with pytest.raises(DynamoValidationError):
            f.validate("yes")

    def test_round_trip(self):
        f = BooleanField()
        f.name = "b"
        assert f.from_dynamo(f.to_dynamo(True)) is True


class TestDateTimeField:
    def test_round_trip(self):
        f = DateTimeField()
        f.name = "dt"
        now = datetime.now(tz=timezone.utc)
        val = f.to_dynamo(now)
        assert isinstance(val, str)
        back = f.from_dynamo(val)
        assert isinstance(back, datetime)
        assert back == now

    def test_auto_now_add_default(self):
        f = DateTimeField(auto_now_add=True)
        f.name = "dt"
        default = f.get_default()
        assert isinstance(default, datetime)


class TestUUIDField:
    def test_default_generated(self):
        import uuid
        f = UUIDField()
        f.name = "pk"
        val = f.get_default()
        uuid.UUID(val)  # should not raise

    def test_invalid_uuid(self):
        f = UUIDField()
        f.name = "pk"
        with pytest.raises(DynamoValidationError):
            f.validate("not-a-uuid")


class TestJSONField:
    def test_dict(self):
        f = JSONField()
        f.name = "j"
        f.validate({"key": "value"})

    def test_list(self):
        f = JSONField()
        f.name = "j"
        f.validate([1, 2, 3])

    def test_invalid(self):
        f = JSONField(nullable=False)
        f.name = "j"
        with pytest.raises(DynamoValidationError):
            f.validate("raw string")


# ══════════════════════════════════════════════════════ model CRUD

class TestDynamoModelCRUD:
    def test_create_and_retrieve(self):
        w = Widget.objects.create(name="Gadget")
        assert w.pk is not None
        fetched = Widget.objects.get(pk=w.pk)
        assert fetched.name == "Gadget"
        assert fetched.score == 0
        assert fetched.active is True

    def test_save_update(self):
        w = Widget.objects.create(name="Before")
        w.name = "After"
        w.save()
        fetched = Widget.objects.get(pk=w.pk)
        assert fetched.name == "After"

    def test_delete(self):
        w = Widget.objects.create(name="ToDelete")
        pk = w.pk
        w.delete()
        with pytest.raises(Widget.DoesNotExist):
            Widget.objects.get(pk=pk)

    def test_refresh_from_db(self):
        w = Widget.objects.create(name="Original")
        # Simulate external update
        w2 = Widget.objects.get(pk=w.pk)
        w2.name = "Changed"
        w2.save()
        w.refresh_from_db()
        assert w.name == "Changed"

    def test_auto_now_add_set_on_create(self):
        w = Widget.objects.create(name="Timed")
        assert isinstance(w.created_at, datetime)

    def test_auto_now_updated_on_save(self):
        import time
        w = Widget.objects.create(name="Clock")
        first_updated = w.updated_at
        time.sleep(0.01)
        w.name = "ClockTick"
        w.save()
        w.refresh_from_db()
        assert w.updated_at >= first_updated

    def test_nullable_field_missing(self):
        w = Widget.objects.create(name="NoMeta")
        assert w.meta is None

    def test_list_field_default(self):
        w = Widget.objects.create(name="Tagged")
        assert w.tags == []


# ══════════════════════════════════════════════════════ queryset

class TestDynamoQuerySet:
    @pytest.fixture(autouse=True)
    def _clean(self, mock_dynamodb):
        ensure_table(Widget)
        Widget.objects.all().delete()

    def _make(self, n=3):
        names = [f"Widget-{i}" for i in range(n)]
        return [Widget.objects.create(name=n, score=i * 10) for i, n in enumerate(names)]

    def test_all(self):
        self._make(3)
        assert Widget.objects.count() == 3

    def test_filter_exact(self):
        self._make(3)
        Widget.objects.create(name="Special", score=999)
        results = Widget.objects.filter(name="Special")
        assert len(list(results)) == 1

    def test_filter_gt(self):
        from decimal import Decimal
        self._make(3)   # scores 0, 10, 20
        results = list(Widget.objects.filter(score__gt=Decimal("5")))
        assert all(w.score > 5 for w in results)

    def test_filter_contains(self):
        self._make(3)   # Widget-0, Widget-1, Widget-2
        Widget.objects.create(name="Completely Different")
        results = list(Widget.objects.filter(name__contains="Widget"))
        assert len(results) == 3

    def test_filter_startswith(self):
        self._make(3)
        Widget.objects.create(name="Zephyr")
        results = list(Widget.objects.filter(name__startswith="Widget"))
        assert len(results) == 3

    def test_filter_in(self):
        ws = self._make(3)
        pks = [ws[0].pk, ws[2].pk]
        results = list(Widget.objects.filter(pk__in=pks))
        assert len(results) == 2

    def test_filter_isnull_true(self):
        Widget.objects.create(name="NoMeta")
        Widget.objects.create(name="HasMeta", meta={"x": 1})
        no_meta = list(Widget.objects.filter(meta__isnull=True))
        assert all(w.meta is None for w in no_meta)

    def test_exclude(self):
        self._make(3)
        Widget.objects.create(name="Exclude-Me", active=False)
        results = list(Widget.objects.exclude(active=False))
        assert all(w.active is not False for w in results)

    def test_get_single(self):
        ws = self._make(1)
        w = Widget.objects.get(pk=ws[0].pk)
        assert w.name == ws[0].name

    def test_get_not_found(self):
        with pytest.raises(Widget.DoesNotExist):
            Widget.objects.get(pk="nonexistent-pk-value")

    def test_get_multiple(self):
        Widget.objects.create(name="Dupe", score=1)
        Widget.objects.create(name="Dupe", score=2)
        with pytest.raises(DynamoMultipleObjectsReturned):
            Widget.objects.get(name="Dupe")

    def test_first(self):
        self._make(3)
        w = Widget.objects.first()
        assert w is not None

    def test_first_empty(self):
        assert Widget.objects.first() is None

    def test_order_by_asc(self):
        self._make(3)
        results = Widget.objects.order_by("score")
        scores = [w.score for w in results]
        assert scores == sorted(scores)

    def test_order_by_desc(self):
        self._make(3)
        results = Widget.objects.order_by("-score")
        scores = [w.score for w in results]
        assert scores == sorted(scores, reverse=True)

    def test_values(self):
        self._make(2)
        dicts = Widget.objects.values("name", "score")
        assert all("name" in d and "score" in d for d in dicts)

    def test_values_no_fields(self):
        w = Widget.objects.create(name="Full")
        dicts = Widget.objects.values()
        assert any(d.get("name") == "Full" for d in dicts)

    def test_queryset_delete(self):
        self._make(3)
        Widget.objects.create(name="Keeper")
        deleted = Widget.objects.filter(name__startswith="Widget").delete()
        assert deleted == 3
        assert Widget.objects.count() == 1

    def test_chained_filters(self):
        Widget.objects.create(name="Alpha", score=50, active=True)
        Widget.objects.create(name="Beta",  score=50, active=False)
        Widget.objects.create(name="Gamma", score=10, active=True)
        from decimal import Decimal
        results = list(
            Widget.objects.filter(score__gte=Decimal("50")).filter(active=True)
        )
        assert len(results) == 1
        assert results[0].name == "Alpha"


# ══════════════════════════════════════════════════════ manager

class TestDynamoManager:
    def test_get_or_create_creates(self):
        w, created = Widget.objects.get_or_create(
            defaults={"score": 7}, name="Unique-One"
        )
        assert created is True
        assert w.score == 7

    def test_get_or_create_gets(self):
        Widget.objects.create(name="AlreadyExists", score=1)
        w, created = Widget.objects.get_or_create(name="AlreadyExists")
        assert created is False
        assert w.name == "AlreadyExists"

    def test_bulk_create(self):
        items = [Widget(name=f"Bulk-{i}", score=i) for i in range(5)]
        Widget.objects.bulk_create(items)
        assert Widget.objects.filter(name__startswith="Bulk").count() == 5

    def test_manager_not_accessible_on_instance(self):
        w = Widget.objects.create(name="Instance")
        with pytest.raises(AttributeError):
            _ = w.objects


# ══════════════════════════════════════════════════════ table management

class TestTableManagement:
    def test_ensure_table_idempotent(self):
        # Calling ensure_table twice should not raise
        ensure_table(Widget)
        ensure_table(Widget)  # second call — table already exists

    def test_delete_then_recreate(self):
        delete_table(Widget)
        ensure_table(Widget)
        # Should be usable again
        w = Widget.objects.create(name="PostDelete")
        assert Widget.objects.get(pk=w.pk).name == "PostDelete"
