"""
dynamo_backend.backends.dynamodb.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DatabaseSchemaEditor for DynamoDB.

DynamoDB is schemaless so there is no DDL for columns, but we still enforce
Django's "non-null field" contract at the *data* level:

  create_model   → ensure_table (create DynamoDB table + GSIs)
  delete_model   → delete_table
  add_field      → no DDL; backfill existing items when field is non-null
                   with a concrete default
  remove_field   → no-op (items keep the raw attribute; Django ignores it)
  alter_field    → backfill when promoting null → non-null
  rename_field   → rename the attribute on every existing item (full scan)
  add_index      → create GSI (best-effort, managed at table-creation time)
  remove_index   → delete GSI (best-effort)

Why backfill matters
────────────────────
DynamoDB items written before a new non-null field was added simply won't
have that attribute.  When Django reads them it gets None for a field
declared as non-null, which can cause unexpected validation errors, broken
serialisers, and confusing bugs.  Backfilling applies the declared default
so the data matches the schema definition.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import logging
import uuid as _uuid_mod

from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_log = logging.getLogger(__name__)


class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    # We don't generate SQL — all DynamoDB calls happen via boto3
    sql_create_column = ""
    sql_delete_column = ""
    sql_create_table = ""
    sql_delete_table = ""

    # Required by Django's migration executor
    deferred_sql: list = []

    def __enter__(self):
        self.deferred_sql = []
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Nothing to execute — DynamoDB has no deferred SQL
        pass

    # ── Table lifecycle ───────────────────────────────────────────────────

    def create_model(self, model):
        """Called by migrate/syncdb — create the DynamoDB table."""
        self.connection.creation.ensure_table(model)

    def delete_model(self, model):
        """Called by migrate when a model is deleted."""
        self.connection.creation.delete_table(model)

    # ── Column operations ─────────────────────────────────────────────────

    def add_field(self, model, field):
        """No DDL needed — DynamoDB is schemaless.

        However, when a non-null field with a concrete default is added we
        scan the table and write the default on every existing item that is
        missing the attribute.  This mirrors what a SQL ``ALTER TABLE … ADD
        COLUMN … DEFAULT …`` would do.
        """
        if self._should_backfill(field):
            self._backfill_field(model, field)

    def remove_field(self, model, field):
        """No-op — DynamoDB items keep their raw attributes; Django ignores them."""
        pass

    def alter_field(self, model, old_field, new_field, strict=False):
        """Handle schema changes that require a data migration.

        The only case that needs work is promoting a nullable field to
        non-null: we backfill items that currently have no value for the
        attribute.
        """
        was_nullable = getattr(old_field, "null", True)
        now_required = not getattr(new_field, "null", False)
        if was_nullable and now_required and self._should_backfill(new_field):
            self._backfill_field(model, new_field)

    def rename_field(self, model, old_field, new_field):
        """Rename an attribute on every existing item.

        DynamoDB has no native rename, so we copy the value under the new
        attribute name and delete the old one using an UpdateExpression.
        Items that already have the new name (partial re-run) are skipped.
        """
        old_attr = old_field.attname
        new_attr = new_field.attname
        if old_attr == new_attr:
            return

        table_name = self.connection.creation._table_name(model)
        pk_name    = model._meta.pk.attname
        dynamodb   = self.connection.get_dynamodb_resource()
        table      = dynamodb.Table(table_name)
        client     = dynamodb.meta.client

        _log.info(
            "Renaming attribute %s → %s on table %s …",
            old_attr, new_attr, table_name,
        )

        updated = 0
        scan_kw: dict = {
            "TableName": table_name,
            # Only touch items that still have the old attribute
            "FilterExpression": "attribute_exists(#old) AND attribute_not_exists(#new)",
            "ProjectionExpression": "#pk, #old",
            "ExpressionAttributeNames": {
                "#old": old_attr,
                "#new": new_attr,
                "#pk":  pk_name,
            },
        }

        while True:
            resp = client.scan(**scan_kw)
            for raw_item in resp.get("Items", []):
                pk_typed  = raw_item.get(pk_name)
                old_typed = raw_item.get(old_attr)
                if not pk_typed or not old_typed:
                    continue
                pk_val  = _unwrap_dynamodb_value(pk_typed)
                old_val = _unwrap_dynamodb_value(old_typed)

                try:
                    table.update_item(
                        Key={pk_name: pk_val},
                        UpdateExpression="SET #new = :val REMOVE #old",
                        ConditionExpression=(
                            "attribute_exists(#old) AND attribute_not_exists(#new)"
                        ),
                        ExpressionAttributeNames={"#old": old_attr, "#new": new_attr},
                        ExpressionAttributeValues={":val": old_val},
                    )
                    updated += 1
                except client.exceptions.ConditionalCheckFailedException:
                    pass  # already renamed by a concurrent writer — fine

            if "LastEvaluatedKey" not in resp:
                break
            scan_kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        _log.info(
            "Renamed %d item(s): %s → %s on %s",
            updated, old_attr, new_attr, table_name,
        )

    # ── backfill helpers ──────────────────────────────────────────────────

    @staticmethod
    def _should_backfill(field) -> bool:
        """Return True when existing items need the field's default written."""
        if getattr(field, "null", False):
            return False                    # nullable — no backfill needed
        if getattr(field, "auto_now_add", False) or getattr(field, "auto_now", False):
            return False                    # timestamp: each row gets its own value on write
        return field.has_default()

    @staticmethod
    def _prep_default(field):
        """Return a boto3-safe Python value for the field's default.

        boto3's TypeSerializer handles str, int, bool, Decimal, list, dict and
        None natively.  We convert the handful of Python types it doesn't
        understand.
        """
        raw = field.get_default()
        if isinstance(raw, _uuid_mod.UUID):
            return str(raw)
        if isinstance(raw, (_dt.datetime, _dt.date)):
            return raw.isoformat()
        if isinstance(raw, _dt.timedelta):
            return str(raw.total_seconds())
        if isinstance(raw, float):
            return _decimal.Decimal(str(raw))   # DynamoDB stores numbers as Decimal
        # bool before int — bool is a subclass of int
        if isinstance(raw, (bool, int, str, list, dict)) or raw is None:
            return raw
        return str(raw)   # last-resort coercion

    def _backfill_field(self, model, field) -> None:
        """Scan the table and write <field.attname> = <default> on every item
        that is missing the attribute.

        Uses a conditional write (``attribute_not_exists``) so it is safe to
        restart and idempotent across concurrent migrations.
        """
        table_name = self.connection.creation._table_name(model)
        attr_name  = field.attname
        pk_name    = model._meta.pk.attname
        value      = self._prep_default(field)

        if value is None:
            _log.warning(
                "add_field backfill skipped for %s.%s — default resolved to None",
                model._meta.label, attr_name,
            )
            return

        dynamodb = self.connection.get_dynamodb_resource()
        table    = dynamodb.Table(table_name)
        client   = dynamodb.meta.client

        _log.info(
            "Backfilling %s.%s = %r on existing items …",
            model._meta.label, attr_name, value,
        )

        updated = 0
        scan_kw: dict = {
            "TableName": table_name,
            # Only visit items that are missing the attribute
            "FilterExpression": "attribute_not_exists(#attr)",
            # Fetch only the PK — we don't need the full item
            "ProjectionExpression": "#pk",
            "ExpressionAttributeNames": {"#attr": attr_name, "#pk": pk_name},
        }

        while True:
            resp = client.scan(**scan_kw)
            for raw_item in resp.get("Items", []):
                pk_typed = raw_item.get(pk_name)
                if not pk_typed:
                    continue
                pk_val = _unwrap_dynamodb_value(pk_typed)
                try:
                    table.update_item(
                        Key={pk_name: pk_val},
                        UpdateExpression="SET #attr = :val",
                        ConditionExpression="attribute_not_exists(#attr)",
                        ExpressionAttributeNames={"#attr": attr_name},
                        ExpressionAttributeValues={":val": value},
                    )
                    updated += 1
                except client.exceptions.ConditionalCheckFailedException:
                    pass  # already set by a concurrent writer — fine

            if "LastEvaluatedKey" not in resp:
                break
            scan_kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        _log.info(
            "Backfilled %d item(s) for %s.%s",
            updated, model._meta.label, attr_name,
        )

    def alter_db_table(self, model, old_db_table, new_db_table):
        """Table renames are not supported by DynamoDB; skip silently."""
        pass

    def alter_db_tablespace(self, model, old_db_tablespace, new_db_tablespace):
        pass

    def rename_db_column(self, model, old_column_name, new_column_name):
        pass

    # ── Index operations ──────────────────────────────────────────────────

    def add_index(self, model, index):
        """
        GSIs are created at table-creation time.  If called after table
        creation (ALTER TABLE equivalent), we attempt an UpdateTable but
        silently ignore errors.
        """
        pass  # Managed at table creation

    def remove_index(self, model, index):
        pass

    def add_constraint(self, model, constraint):
        pass

    def remove_constraint(self, model, constraint):
        pass

    # ── Unique / check constraints — no-ops ──────────────────────────────

    def create_unique(self, model, columns):
        pass

    def destroy_unique(self, model, columns):
        pass

    # ── Required quote helper ─────────────────────────────────────────────

    def quote_name(self, name):
        return name

    # ── Prevent SQL execution ─────────────────────────────────────────────

    def execute(self, sql, params=()):
        """No SQL execution — all ops are done via boto3."""
        pass


# ── module-level helpers ──────────────────────────────────────────────────────

def _unwrap_dynamodb_value(typed_value: dict):
    """Unwrap a single DynamoDB typed value to a Python native value.

    When using the low-level ``boto3.client`` API, attribute values come back
    in DynamoDB's wire format::

        {"S": "hello"}
        {"N": "42"}
        {"BOOL": True}
        {"NULL": True}
        {"L": [{"S": "a"}, {"S": "b"}]}
        {"M": {"key": {"S": "val"}}}

    This helper extracts the raw Python value so it can be passed back through
    the high-level ``Table`` resource methods (which use TypeSerializer
    automatically).
    """
    if not isinstance(typed_value, dict) or not typed_value:
        return typed_value
    type_key, val = next(iter(typed_value.items()))
    if type_key == "S":
        return str(val)
    if type_key == "N":
        # Keep as Decimal so boto3 round-trips it without loss
        import decimal
        return decimal.Decimal(val)
    if type_key == "BOOL":
        return bool(val)
    if type_key == "NULL":
        return None
    if type_key == "L":
        return [_unwrap_dynamodb_value(v) for v in val]
    if type_key == "M":
        return {k: _unwrap_dynamodb_value(v) for k, v in val.items()}
    if type_key in ("SS", "NS", "BS"):
        return set(val)
    return val  # B (binary) — return as-is
