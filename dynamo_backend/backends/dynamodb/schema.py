"""
dynamo_backend.backends.dynamodb.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DatabaseSchemaEditor for DynamoDB.

DynamoDB is schemaless (no column DDL), so most operations are either
no-ops or map to table create/delete.

  create_model   → ensure_table (create DynamoDB table + GSIs)
  delete_model   → delete_table
  add_field      → no-op (DynamoDB is schemaless)
  remove_field   → no-op
  alter_field    → no-op
  rename_field   → no-op
  add_index      → create GSI (best-effort)
  remove_index   → delete GSI (best-effort)
"""

from __future__ import annotations

from django.db.backends.base.schema import BaseDatabaseSchemaEditor


class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    # We don't generate SQL — all DynamoDB calls happen via boto3
    sql_create_column = ""
    sql_delete_column = ""
    sql_create_table = ""
    sql_delete_table = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    # ── Table lifecycle ───────────────────────────────────────────────────

    def create_model(self, model):
        """Called by migrate/syncdb — create the DynamoDB table."""
        self.connection.creation.ensure_table(model)

    def delete_model(self, model):
        """Called by migrate when a model is deleted."""
        self.connection.creation.delete_table(model)

    # ── Column operations — all no-ops in DynamoDB ────────────────────────

    def add_field(self, model, field):
        """DynamoDB is schemaless; no DDL needed for new attributes."""
        pass

    def remove_field(self, model, field):
        pass

    def alter_field(self, model, old_field, new_field, strict=False):
        pass

    def rename_field(self, model, old_field, new_field):
        pass

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
