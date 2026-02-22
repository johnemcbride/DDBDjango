"""
dynamo_backend.backends.dynamodb.compiler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Translates Django ORM Query objects into DynamoDB API calls.

Translation strategy
────────────────────
SELECT
  WHERE pk = value            → GetItem
  WHERE pk IN [v1, v2, ...]   → BatchGetItem
  WHERE indexed_field = value → Query  (GSI, O(results))
  anything else               → Scan  (with optional FilterExpression)
  COUNT aggregate             → Scan(Select='COUNT')

INSERT                        → PutItem
UPDATE                        → PutItem (full-item replace after fetch-modify)
DELETE                        → DeleteItem (scan + batch for non-pk deletes)

Config parameters (DATABASES['dynamodb']['OPTIONS'])
─────────────────────────────────────────────────────
scan_on_filter    bool  default True    Allow full-table scans for non-pk filters
consistent_read   bool  default False   Use strongly consistent reads
batch_chunk_size  int   default 25      BatchGetItem chunk size (max 100)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

try:
    from django.db.models.sql.compiler import GET_ITERATOR_CHUNK_SIZE
except ImportError:
    GET_ITERATOR_CHUNK_SIZE = 2000

from django.db.models.sql.compiler import (
    SQLCompiler as BaseSQLCompiler,
    SQLInsertCompiler as BaseSQLInsertCompiler,
    SQLUpdateCompiler as BaseSQLUpdateCompiler,
    SQLDeleteCompiler as BaseSQLDeleteCompiler,
    SQLAggregateCompiler as BaseSQLAggregateCompiler,
)
from django.db.models.sql.constants import MULTI, SINGLE, NO_RESULTS, CURSOR


# ──────────────────────────────────────────────────── connection helpers


def _get_boto_resource(connection):
    return connection.get_dynamodb_resource()


def _table_name(connection, model) -> str:
    prefix = connection.settings_dict.get("OPTIONS", {}).get("table_prefix", "")
    return prefix + model._meta.db_table


def _pk_col(model) -> str:
    """Return the attname of the model's primary key (e.g. 'id')."""
    return model._meta.pk.attname


def _option(connection, key, default):
    return connection.settings_dict.get("OPTIONS", {}).get(key, default)


# ────────────────────────────────────────────── value coercion helpers


def _to_dynamo_value(field, value):
    """Convert a Python value to a DynamoDB-storable scalar/collection."""
    if value is None:
        return None

    import django.db.models.fields as F
    from django.db.models.fields.related import ForeignKey

    # ForeignKey — delegate to the related model's pk field
    if isinstance(field, ForeignKey):
        return _to_dynamo_value(field.remote_field.model._meta.pk, value)

    # UUID → string
    if isinstance(field, F.UUIDField):
        return str(value)

    # Datetime/Date/Time → ISO-8601 string (must be before bool/int checks)
    if hasattr(value, "isoformat"):
        return value.isoformat()

    # bool (must check before int — bool is a subclass of int in Python)
    if isinstance(value, bool):
        return value

    # int
    if isinstance(value, int):
        return value

    # float → Decimal for DynamoDB precision
    if isinstance(value, float):
        return Decimal(str(value))

    # Decimal pass-through
    if isinstance(value, Decimal):
        return value

    return value


def _from_dynamo_value(field, value):
    """Convert a DynamoDB stored value back to the expected Python type."""
    if value is None:
        return None

    import django.db.models.fields as F
    from django.db.models.fields.related import ForeignKey
    from django.utils import timezone as dj_tz

    # ForeignKey — unwrap to the related model's pk field type
    if isinstance(field, ForeignKey):
        related_pk = field.remote_field.model._meta.pk
        return _from_dynamo_value(related_pk, value)

    # UUID
    if isinstance(field, F.UUIDField):
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return value

    # DateTime
    if isinstance(field, F.DateTimeField):
        if isinstance(value, str):
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(value)
                from django.conf import settings
                if getattr(settings, "USE_TZ", False) and not dj_tz.is_aware(dt):
                    from datetime import timezone as _tz
                    dt = dt.replace(tzinfo=_tz.utc)
                return dt
            except (ValueError, TypeError):
                return value
        return value

    # Date
    if isinstance(field, F.DateField):
        if isinstance(value, str):
            from datetime import date
            try:
                return date.fromisoformat(value)
            except (ValueError, TypeError):
                return value
        return value

    # Numeric: DynamoDB Decimal → Python int/float
    # Also handle string → int for AutoField PKs stored as DynamoDB 'S' keys.
    _int_fields = (
        F.IntegerField, F.AutoField, F.BigIntegerField, F.SmallIntegerField,
        F.PositiveIntegerField, F.PositiveBigIntegerField, F.PositiveSmallIntegerField,
    )
    if isinstance(field, _int_fields):
        if isinstance(value, Decimal):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except (ValueError, TypeError):
                return value
        if isinstance(value, int):
            return value
        return value

    if isinstance(value, Decimal):
        if isinstance(field, F.FloatField):
            return float(value)
        # DecimalField: stay as Decimal
        return value

    return value


def _serialize_pk(pk_field, pk_value) -> str | None:
    """Serialize a PK value to the string stored as the DynamoDB hash key."""
    if pk_value is None:
        return None
    val = _to_dynamo_value(pk_field, pk_value)
    return str(val) if val is not None else None


# ────────────────────────────────────────── WHERE clause parsing


def _parse_where(query):
    """
    Inspect query.where and return (pk_value, pk_values, conditions).

    pk_value  – single string PK   → GetItem
    pk_values – list of string PKs → BatchGetItem
    conditions – list[(attname, lookup_name, value, negated)] → Scan
    """
    node = query.where
    if node is None or not node.children:
        return None, None, []

    pk_attname = _pk_col(query.model)

    # Single-child exact-pk or pk-in at the top level
    if len(node.children) == 1 and not node.negated:
        child = node.children[0]
        if _is_lookup(child):
            col = _lookup_attname(child)
            if col == pk_attname:
                if child.lookup_name == "exact":
                    pk_field = query.model._meta.pk
                    return _serialize_pk(pk_field, child.rhs), None, []
                if child.lookup_name == "in":
                    pk_field = query.model._meta.pk
                    return None, [_serialize_pk(pk_field, v) for v in child.rhs], []

    # Fall back to Scan
    conditions: list = []
    _collect_conditions(node, False, conditions)
    return None, None, conditions


def _is_lookup(child) -> bool:
    return (
        hasattr(child, "lhs")
        and hasattr(child, "rhs")
        and hasattr(child, "lookup_name")
    )


def _lookup_attname(child) -> str | None:
    lhs = child.lhs
    target = getattr(lhs, "target", lhs)
    return getattr(target, "attname", None) or getattr(target, "column", None)


def _collect_conditions(node, parent_negated: bool, out: list) -> None:
    effective_negated = parent_negated ^ node.negated
    for child in node.children:
        if hasattr(child, "children"):
            _collect_conditions(child, effective_negated, out)
        elif _is_lookup(child):
            col = _lookup_attname(child)
            if col is not None:
                out.append((col, child.lookup_name, child.rhs, effective_negated))


def _dynamo_safe(value):
    """Coerce a Python value to a type boto3 DynamoDB can serialize."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if hasattr(value, "isoformat"):  # datetime / date / time
        return value.isoformat()
    return value


def _build_filter_expression(conditions: list, model):
    """
    Build a boto3 ConditionExpression from conditions.
    Returns (expr_or_None, is_empty_result).
    """
    from boto3.dynamodb.conditions import Attr

    expr = None
    has_empty_in = False

    for col, lookup_name, value, negated in conditions:
        attr = Attr(col)
        value = _dynamo_safe(value)

        if lookup_name in ("exact", "iexact"):
            cond = attr.eq(value)
        elif lookup_name in ("contains", "icontains"):
            cond = attr.contains(value)
        elif lookup_name in ("startswith", "istartswith"):
            cond = attr.begins_with(value)
        elif lookup_name == "gt":
            cond = attr.gt(value)
        elif lookup_name == "gte":
            cond = attr.gte(value)
        elif lookup_name == "lt":
            cond = attr.lt(value)
        elif lookup_name == "lte":
            cond = attr.lte(value)
        elif lookup_name == "range":
            cond = attr.between(*value)
        elif lookup_name == "in":
            vals = [_dynamo_safe(v) for v in value]
            if not vals:
                has_empty_in = True
                continue
            cond = Attr(col).eq(vals[0])
            for v in vals[1:]:
                cond = cond | Attr(col).eq(v)
        elif lookup_name == "isnull":
            cond = attr.not_exists() if value else attr.exists()
        else:
            cond = attr.eq(value)

        if negated:
            cond = ~cond

        expr = cond if expr is None else (expr & cond)

    if has_empty_in and expr is None:
        return None, True  # empty IN with no other conditions → no results
    return expr, False


# ──────────────────────────────────── result field list & row building


def _get_select_fields(query) -> list:
    """
    Return the ordered list of concrete Field objects corresponding to the
    tuple positions produced by execute_sql — mirrors what ModelIterable assumes.
    """
    if query.select:
        return [
            col.target
            for col in query.select
            if hasattr(col, "target")
        ]

    model = query.model
    deferred_names, defer_flag = query.deferred_loading
    all_concrete = list(model._meta.concrete_fields)

    if not deferred_names:
        return all_concrete
    if defer_flag:
        # defer_flag=True means deferred_names are the EXCLUDED fields
        return [f for f in all_concrete if f.attname not in deferred_names]
    # defer_flag=False means deferred_names are the ONLY included ones
    return [f for f in all_concrete if f.attname in deferred_names]


def _item_to_row(item: dict, fields: list) -> tuple:
    return tuple(_from_dynamo_value(f, item.get(f.attname)) for f in fields)


# ──────────────────────────────────────────── DynamoDB I/O helpers


def _get_table(connection, model):
    return _get_boto_resource(connection).Table(_table_name(connection, model))


def _do_get_item(connection, model, pk_value: str) -> list:
    table = _get_table(connection, model)
    pk_col = _pk_col(model)
    consistent = _option(connection, "consistent_read", False)
    resp = table.get_item(Key={pk_col: pk_value}, ConsistentRead=consistent)
    item = resp.get("Item")
    return [item] if item else []


def _do_batch_get(connection, model, pk_values: list) -> list:
    pk_col = _pk_col(model)
    tbl_name = _table_name(connection, model)
    dynamodb = _get_boto_resource(connection)
    chunk_size = _option(connection, "batch_chunk_size", 25)
    consistent = _option(connection, "consistent_read", False)

    items: list = []
    for i in range(0, len(pk_values), chunk_size):
        chunk = pk_values[i : i + chunk_size]
        request = {
            tbl_name: {
                "Keys": [{pk_col: v} for v in chunk],
                "ConsistentRead": consistent,
            }
        }
        resp = dynamodb.batch_get_item(RequestItems=request)
        items.extend(resp.get("Responses", {}).get(tbl_name, []))
        unprocessed = resp.get("UnprocessedKeys", {})
        while unprocessed:
            resp = dynamodb.batch_get_item(RequestItems=unprocessed)
            items.extend(resp.get("Responses", {}).get(tbl_name, []))
            unprocessed = resp.get("UnprocessedKeys", {})
    return items


def _detect_gsi_query(conditions: list, model):
    """
    If *conditions* is a single non-negated exact-equality on a non-PK
    field that carries a GSI (db_index=True or unique=True), return
    ``(index_name, key_col, key_value)``.  Otherwise return ``None``.

    GSI names follow the convention created by the schema editor:
    ``{attname}-index``  (e.g. ``author_id-index``, ``slug-index``).
    """
    if len(conditions) != 1:
        return None
    col, lookup_name, value, negated = conditions[0]
    if negated or lookup_name not in ("exact", "iexact"):
        return None
    pk_attname = _pk_col(model)
    if col == pk_attname:
        return None
    for field in model._meta.concrete_fields:
        if field.attname == col or field.column == col:
            if field.attname == pk_attname:
                return None
            if getattr(field, "db_index", False) or getattr(field, "unique", False):
                return f"{col}-index", col, value
            return None
    return None


def _do_gsi_query(
    connection, model, index_name: str, key_col: str, key_value,
    scan_limit: int | None = None,
) -> list:
    """Query a GSI using KeyConditionExpression — O(results), not O(table).

    Paginates automatically using LastEvaluatedKey, stopping early when
    *scan_limit* items have been collected.
    """
    from boto3.dynamodb.conditions import Key

    table = _get_table(connection, model)
    dv = _dynamo_safe(key_value)
    kwargs: dict[str, Any] = {
        "IndexName": index_name,
        "KeyConditionExpression": Key(key_col).eq(dv),
    }
    if scan_limit is not None:
        kwargs["Limit"] = scan_limit

    items: list = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        if scan_limit is not None and len(items) >= scan_limit:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _collect_conditions_for_alias(node, target_alias: str, parent_negated: bool, out: list) -> None:
    """Walk query.where and collect Lookup children whose lhs.alias matches *target_alias*."""
    if node is None or not hasattr(node, "children"):
        return
    effective_negated = parent_negated ^ node.negated
    for child in node.children:
        if hasattr(child, "children"):
            _collect_conditions_for_alias(child, target_alias, effective_negated, out)
        elif _is_lookup(child):
            lhs = child.lhs
            if getattr(lhs, "alias", None) == target_alias:
                col = _lookup_attname(child)
                out.append((col, child.rhs, child.lookup_name, effective_negated))


def _detect_m2m_join(query):
    """
    Detect a simple M2M through-table JOIN pattern in *query*.

    The signature in alias_map is:
      - One BaseTable  (the target model, e.g. auth_group)
      - One Join with refcount > 0  (the through table, e.g. auth_user_groups)
      - Optionally one Join with refcount == 0  (source model, unused)

    The WHERE condition(s) reference the through-table alias.

    Returns (through_table_name, through_conditions) or None.
    through_conditions: list of (col, rhs, lookup_name, negated)
    """
    from django.db.models.sql.datastructures import Join

    active_joins = [
        (alias, info)
        for alias, info in query.alias_map.items()
        if isinstance(info, Join) and query.alias_refcount.get(alias, 0) > 0
    ]

    if len(active_joins) != 1:
        return None

    through_alias, join_info = active_joins[0]
    through_table = join_info.table_name

    through_conditions: list = []
    _collect_conditions_for_alias(query.where, through_alias, False, through_conditions)

    if not through_conditions:
        return None

    return through_table, through_conditions


def _do_m2m_join(connection, query, through_table_name: str, through_conditions: list):
    """
    Execute a detected M2M join as a two-step DynamoDB query.

    Step 1 — Filter through table for the target PKs (uses GSI when available).
    Step 2 — BatchGetItem the target model with those PKs.

    Returns a list of DynamoDB items (same shape as _do_batch_get), or None if
    the pattern is too complex to translate (caller should then raise/fallback).
    """
    from django.apps import apps as django_apps

    target_model = query.model

    # Find through model by table name
    through_model = None
    for app_config in django_apps.get_app_configs():
        for model in app_config.get_models():
            if model._meta.db_table == through_table_name:
                through_model = model
                break
        if through_model:
            break

    if through_model is None:
        return None

    # Build ORM filter kwargs from WHERE conditions on the through table.
    # Only support non-negated exact matches for the through-table filter.
    filter_kwargs: dict = {}
    for col, value, lookup, negated in through_conditions:
        if negated or lookup not in ("exact", "iexact"):
            return None  # too complex
        filter_kwargs[col] = value

    if not filter_kwargs:
        return None

    # Identify the FK on the through model that points to target_model
    # (it will be the one whose attname is NOT in filter_kwargs).
    target_fk_attname = None
    for field in through_model._meta.concrete_fields:
        if field.attname in filter_kwargs:
            continue
        if (
            hasattr(field, "remote_field")
            and field.remote_field
            and getattr(field.remote_field, "model", None) == target_model
        ):
            target_fk_attname = field.attname
            break

    if target_fk_attname is None:
        return None

    # Step 1: query the through table for target PKs
    target_ids = list(
        through_model._default_manager
        .filter(**filter_kwargs)
        .values_list(target_fk_attname, flat=True)
    )

    if not target_ids:
        return []

    # Step 2: BatchGetItem the target model
    pk_values = [_serialize_pk(target_model._meta.pk, v) for v in target_ids]
    return _do_batch_get(connection, target_model, pk_values)


def _do_scan(connection, model, conditions: list, scan_limit: int | None = None) -> list:
    """Full-table scan with an optional early-stop at *scan_limit* items.

    When *scan_limit* is provided we pass ``Limit=scan_limit`` to DynamoDB so
    that each page evaluates at most that many items, and we stop paginating
    once we have accumulated the requested number.  This avoids iterating
    through millions of rows when only a small page is needed (e.g. admin list).
    """
    table = _get_table(connection, model)
    kwargs: dict[str, Any] = {}
    filter_expr, is_empty = _build_filter_expression(conditions, model)
    if is_empty:
        return []
    if filter_expr is not None:
        kwargs["FilterExpression"] = filter_expr
    if scan_limit is not None:
        kwargs["Limit"] = scan_limit

    items: list = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        if scan_limit is not None and len(items) >= scan_limit:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _do_count_scan(connection, model, conditions: list) -> int:
    table = _get_table(connection, model)
    kwargs: dict[str, Any] = {"Select": "COUNT"}
    filter_expr, is_empty = _build_filter_expression(conditions, model)
    if is_empty:
        return 0
    if filter_expr is not None:
        kwargs["FilterExpression"] = filter_expr

    total = 0
    while True:
        resp = table.scan(**kwargs)
        total += resp.get("Count", 0)
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return total


def _apply_ordering(items: list, query) -> list:
    """Sort items in Python (DynamoDB has no ORDER BY)."""
    orderings = list(query.order_by) if query.order_by else []
    if not orderings:
        return items

    for order in reversed(orderings):
        reverse = order.startswith("-")
        col = order.lstrip("-").rsplit(".", 1)[-1]
        try:
            items = sorted(
                items,
                key=lambda x: (x.get(col) is None, x.get(col)),
                reverse=reverse,
            )
        except TypeError:
            pass
    return items


def _apply_limits(items: list, query) -> list:
    low = query.low_mark or 0
    high = query.high_mark
    if low or high is not None:
        items = items[low:high]
    return items


# ────────────────────────────────────────────────────── Compilers


class SQLCompiler(BaseSQLCompiler):
    """SELECT compiler — translates Django Query to DynamoDB GetItem/Scan."""

    def _setup_klass_info(self):
        """
        Manually populate self.select, self.klass_info, and
        self.annotation_col_map without calling pre_sql_setup (which can
        mutate query state and cause unexpected side-effects when we bypass
        SQL generation entirely).

        Returns the ordered list of Field objects matching the row tuples we
        will produce.
        """
        model = self.query.model
        fields = _get_select_fields(self.query)

        # Build a minimal self.select: list of (expr, alias)
        # Each entry corresponds to one field in the same order as `fields`.
        from django.db.models.expressions import Col
        self.select = [(Col(f.column, f, model), None) for f in fields]

        # klass_info tells ModelIterable which slice of each row is model data.
        self.klass_info = {
            "model": model,
            "select_fields": list(range(len(fields))),
            "related_klass_infos": [],
        }

        # No annotations.
        self.annotation_col_map = {}

        return fields

    def execute_sql(
        self,
        result_type=MULTI,
        chunked_fetch=False,
        chunk_size=GET_ITERATOR_CHUNK_SIZE,
    ):
        if result_type == NO_RESULTS:
            return

        model = self.query.model

        # COUNT aggregate
        if self.query.annotations:
            return self._execute_aggregate(result_type)

        # Populate self.select, self.klass_info, self.annotation_col_map
        # without calling pre_sql_setup (avoids SQL-layer side effects).
        fields = self._setup_klass_info()

        # ── M2M through-table JOIN detection ─────────────────────────────
        # Transparently handles any ManyToManyField (auth.User.groups, etc.)
        # without patching model descriptors.  Two-step:  filter through
        # table → BatchGetItem target model.
        m2m = _detect_m2m_join(self.query)
        if m2m is not None:
            through_table, through_conditions = m2m
            result = _do_m2m_join(self.connection, self.query, through_table, through_conditions)
            if result is not None:
                items = result
                items = _apply_ordering(items, self.query)
                items = _apply_limits(items, self.query)
                rows = [_item_to_row(item, fields) for item in items]
                if result_type == SINGLE:
                    return rows[0] if rows else None
                if result_type == CURSOR:
                    class _Cursor:
                        def __init__(self, rows):
                            self._rows = rows
                        def fetchall(self):
                            return self._rows
                        def fetchone(self):
                            return self._rows[0] if self._rows else None
                    return _Cursor(rows)
                return [rows]

        # ── Normal single-table path ──────────────────────────────────────
        # Parse WHERE
        pk_value, pk_values, conditions = _parse_where(self.query)

        # Execute DynamoDB call
        if pk_value is not None:
            items = _do_get_item(self.connection, model, pk_value)
        elif pk_values is not None:
            items = _do_batch_get(self.connection, model, pk_values)
        else:
            scan_limit = self.query.high_mark  # None means no limit
            gsi = _detect_gsi_query(conditions, model)
            if gsi is not None:
                index_name, key_col, key_value = gsi
                items = _do_gsi_query(
                    self.connection, model, index_name, key_col, key_value,
                    scan_limit=scan_limit,
                )
            else:
                if not _option(self.connection, "scan_on_filter", True) and conditions:
                    raise RuntimeError(
                        "DynamoDB: scan_on_filter=False but a non-pk filter was "
                        "requested. Add a GSI or enable scan_on_filter."
                    )
                # Pass high_mark as scan_limit so we don't read the whole table
                # when Django only needs one page (e.g. admin changelist).
                items = _do_scan(self.connection, model, conditions, scan_limit=scan_limit)

        items = _apply_ordering(items, self.query)
        items = _apply_limits(items, self.query)

        # Build rows — no extra_select offset needed (we bypass SQL entirely)
        rows = [_item_to_row(item, fields) for item in items]

        if result_type == SINGLE:
            return rows[0] if rows else None

        if result_type == CURSOR:
            class _Cursor:
                def __init__(self, rows):
                    self._rows = rows
                def fetchall(self):
                    return self._rows
                def fetchone(self):
                    return self._rows[0] if self._rows else None
            return _Cursor(rows)

        return [rows]  # MULTI

    def _execute_aggregate(self, result_type):
        _, _, conditions = _parse_where(self.query)
        count = _do_count_scan(self.connection, self.query.model, conditions)
        row = (count,)
        return row if result_type == SINGLE else [[row]]

    def has_results(self):
        """Used by QuerySet.exists()."""
        model = self.query.model

        # M2M join check
        m2m = _detect_m2m_join(self.query)
        if m2m is not None:
            through_table, through_conditions = m2m
            result = _do_m2m_join(self.connection, self.query, through_table, through_conditions)
            if result is not None:
                return bool(result)

        pk_value, pk_values, conditions = _parse_where(self.query)

        if pk_value is not None:
            return bool(_do_get_item(self.connection, model, pk_value))
        if pk_values is not None:
            return bool(_do_batch_get(self.connection, model, pk_values[:1]))
        gsi = _detect_gsi_query(conditions, model)
        if gsi is not None:
            index_name, key_col, key_value = gsi
            items = _apply_limits(
                _do_gsi_query(self.connection, model, index_name, key_col, key_value, scan_limit=1),
                self.query,
            )
            return bool(items)
        # For exists() we only need 1 item — stop after the first DynamoDB page.
        items = _apply_limits(_do_scan(self.connection, model, conditions, scan_limit=1), self.query)
        return bool(items)

    def results_iter(
        self,
        results=None,
        tuple_expected=False,
        chunked_fetch=False,
        chunk_size=GET_ITERATOR_CHUNK_SIZE,
    ):
        """
        Yield individual row tuples.

        We intentionally skip the from_db_value converters that the SQL-based
        base implementation applies.  Our _from_dynamo_value() function already
        converts every DynamoDB value to the correct Python type when building
        the row, so applying from_db_value() on top would cause double-decoding
        (e.g. JSONField.from_db_value tries json.loads() on an already-decoded
        Python list).
        """
        if results is None:
            results = self.execute_sql(
                MULTI, chunked_fetch=chunked_fetch, chunk_size=chunk_size
            )
        if results is None:
            return

        for batch in results:
            for row in batch:
                yield row


class SQLInsertCompiler(BaseSQLInsertCompiler):
    """INSERT compiler — translates to DynamoDB PutItem."""

    def execute_sql(self, returning_fields=None):
        model = self.query.model
        table = _get_table(self.connection, model)
        pk_field = model._meta.pk
        pk_attname = pk_field.attname
        results = []

        for obj in self.query.objs:
            item: dict = {}
            for field in self.query.fields:
                # Use pre_save to get the Python-level value (e.g. UUID objects,
                # datetime objects, etc.).  Do NOT call get_db_prep_save — that
                # converts values for SQL (e.g. UUID → 32-char hex without dashes)
                # which would create a key-format mismatch with _serialize_pk.
                value = field.pre_save(obj, add=True)
                converted = _to_dynamo_value(field, value)
                if converted is not None:
                    item[field.attname] = converted
                # Reflect back to the instance so callers see the saved value
                current = getattr(obj, field.attname, None)
                if value != current:
                    setattr(obj, field.attname, value)

            # Generate PK if missing
            if not item.get(pk_attname):
                import random
                import django.db.models.fields as F
                if isinstance(pk_field, F.UUIDField):
                    new_pk = uuid.uuid4()
                    setattr(obj, pk_attname, new_pk)
                    item[pk_attname] = str(new_pk)
                elif isinstance(pk_field, (F.AutoField, F.BigAutoField, F.SmallAutoField)):
                    # Generate a random integer PK.  Store it as a string in DynamoDB
                    # (hash key AttributeType 'S') but keep it as an int on the Python
                    # object so that Django's IntegerField.get_prep_value() works.
                    new_pk = random.getrandbits(31)  # fits in a 32-bit signed int
                    setattr(obj, pk_attname, new_pk)
                    item[pk_attname] = str(new_pk)
                else:
                    new_pk = str(uuid.uuid4())
                    setattr(obj, pk_attname, new_pk)
                    item[pk_attname] = new_pk

            table.put_item(Item=item)
            results.append(item[pk_attname])

        if returning_fields:
            return [(r,) for r in results]
        return []


class SQLUpdateCompiler(BaseSQLUpdateCompiler):
    """UPDATE compiler — fetch → modify fields → put back."""

    def execute_sql(self, result_type):
        model = self.query.model
        table = _get_table(self.connection, model)
        pk_col = _pk_col(model)

        pk_value, pk_values, conditions = _parse_where(self.query)

        if pk_value is not None:
            items = _do_get_item(self.connection, model, pk_value)
        elif pk_values is not None:
            items = _do_batch_get(self.connection, model, pk_values)
        else:
            items = _do_scan(self.connection, model, conditions)

        updated = 0
        for item in items:
            for field, _model_cls, value in self.query.values:
                # Use Python-level value directly — do not call get_db_prep_save
                # which applies SQL-specific conversions (e.g. UUID → hex string).
                converted = _to_dynamo_value(field, value)
                if converted is not None:
                    item[field.attname] = converted
                else:
                    item.pop(field.attname, None)
            table.put_item(Item=item)
            updated += 1

        return updated


class SQLDeleteCompiler(BaseSQLDeleteCompiler):
    """DELETE compiler — translates to DynamoDB DeleteItem."""

    def execute_sql(self, result_type):
        model = self.query.model
        table = _get_table(self.connection, model)
        pk_col = _pk_col(model)

        pk_value, pk_values, conditions = _parse_where(self.query)

        if pk_value is not None:
            table.delete_item(Key={pk_col: pk_value})
            return 1

        if pk_values is not None:
            with table.batch_writer() as batch:
                for v in pk_values:
                    batch.delete_item(Key={pk_col: v})
            return len(pk_values)

        items = _do_scan(self.connection, model, conditions)
        with table.batch_writer() as batch:
            for item in items:
                pk_val = item.get(pk_col)
                if pk_val is not None:
                    batch.delete_item(Key={pk_col: pk_val})
        return len(items)


class SQLAggregateCompiler(BaseSQLAggregateCompiler):
    """Aggregate compiler — COUNT only."""

    def execute_sql(self, result_type=MULTI):
        _, _, conditions = _parse_where(self.query)
        count = _do_count_scan(self.connection, self.query.model, conditions)
        row = (count,)
        return row if result_type == SINGLE else [[row]]
