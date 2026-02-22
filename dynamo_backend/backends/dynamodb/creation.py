"""
dynamo_backend.backends.dynamodb.creation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DatabaseCreation — creates and drops DynamoDB tables for test runs and
migrate / makemigrations.

Table design
────────────
Each Django model maps to one DynamoDB table:

  table_name  = OPTIONS.get('table_prefix', '') + model._meta.db_table
  hash_key    = model._meta.pk.attname   (string type; UUID stored as str)

Global Secondary Indexes (GSIs) are created for every field that has
db_index=True or is a ForeignKey (since FK reverse lookups need a scan
on the FK column).  This is controlled by OPTIONS['auto_gsi'] (default True).

Read/write capacity
───────────────────
For local dev / LocalStack the table is created in PAY_PER_REQUEST mode.
Set OPTIONS['billing_mode'] to 'PROVISIONED' and supply
OPTIONS['read_capacity'] / OPTIONS['write_capacity'] for production.
"""

from __future__ import annotations

import time

from botocore.exceptions import ClientError
from django.db.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):

    # ── table helpers ─────────────────────────────────────────────────────

    def _dynamodb(self):
        return self.connection.get_dynamodb_resource()

    def _client(self):
        return self._dynamodb().meta.client

    def _table_name(self, model_or_name) -> str:
        prefix = self.connection.settings_dict.get("OPTIONS", {}).get("table_prefix", "")
        if isinstance(model_or_name, str):
            return prefix + model_or_name
        return prefix + model_or_name._meta.db_table

    def _opt(self, key, default=None):
        return self.connection.settings_dict.get("OPTIONS", {}).get(key, default)

    # ── public API used by SchemaEditor & tests ──────────────────────────

    def ensure_table(self, model) -> None:
        """Create the DynamoDB table for *model* if it doesn't already exist."""
        table_name = self._table_name(model)
        pk_field = model._meta.pk
        pk_attname = pk_field.attname

        # Attribute definitions start with just the hash key
        attr_defs = [{"AttributeName": pk_attname, "AttributeType": "S"}]
        key_schema = [{"AttributeName": pk_attname, "KeyType": "HASH"}]

        # GSIs for indexed / FK fields
        gsis = []
        if self._opt("auto_gsi", True):
            gsi_attrs: set[str] = set()
            for field in model._meta.get_fields():
                # Check db_index or ForeignKey
                is_indexed = getattr(field, "db_index", False)
                from django.db.models.fields.related import ForeignKey
                is_fk = isinstance(field, ForeignKey)
                if (is_indexed or is_fk) and hasattr(field, "attname"):
                    col = field.attname
                    if col != pk_attname and col not in gsi_attrs:
                        gsi_attrs.add(col)
                        attr_defs.append(
                            {"AttributeName": col, "AttributeType": "S"}
                        )
                        gsis.append({
                            "IndexName": f"{col}-index",
                            "KeySchema": [
                                {"AttributeName": col, "KeyType": "HASH"}
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                        })

        billing_mode = self._opt("billing_mode", "PAY_PER_REQUEST")
        kwargs: dict = {
            "TableName": table_name,
            "AttributeDefinitions": attr_defs,
            "KeySchema": key_schema,
            "BillingMode": billing_mode,
        }
        if billing_mode == "PROVISIONED":
            kwargs["ProvisionedThroughput"] = {
                "ReadCapacityUnits": self._opt("read_capacity", 5),
                "WriteCapacityUnits": self._opt("write_capacity", 5),
            }
        if gsis:
            if billing_mode == "PROVISIONED":
                for gsi in gsis:
                    gsi["ProvisionedThroughput"] = {
                        "ReadCapacityUnits": self._opt("read_capacity", 5),
                        "WriteCapacityUnits": self._opt("write_capacity", 5),
                    }
            kwargs["GlobalSecondaryIndexes"] = gsis

        dynamodb = self._dynamodb()
        try:
            table = dynamodb.create_table(**kwargs)
            # Wait until table is active (important for real AWS)
            table.meta.client.get_waiter("table_exists").wait(
                TableName=table_name,
                WaiterConfig={"MaxAttempts": 10, "Delay": 2},
            )
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ResourceInUseException", "TableAlreadyExistsException"):
                pass  # already exists — fine
            else:
                raise

    def delete_table(self, model) -> None:
        """Drop the DynamoDB table for *model* (silently if it doesn't exist)."""
        table_name = self._table_name(model)
        try:
            tbl = self._dynamodb().Table(table_name)
            tbl.delete()
            tbl.meta.client.get_waiter("table_not_exists").wait(
                TableName=table_name,
                WaiterConfig={"MaxAttempts": 10, "Delay": 2},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in (
                "ResourceNotFoundException",
                "TableNotFoundException",
            ):
                pass
            else:
                raise

    # ── Test database lifecycle ───────────────────────────────────────────

    def create_test_db(self, verbosity=1, autoclobber=False, serialize=False, keepdb=False):
        """
        Create all DynamoDB tables for installed apps that use the 'dynamodb' router.
        """
        from django.apps import apps as django_apps

        if verbosity >= 1:
            print("Creating DynamoDB test tables...")

        for app_config in django_apps.get_app_configs():
            for model in app_config.get_models():
                if self._model_uses_this_db(model):
                    try:
                        if not keepdb:
                            self.delete_table(model)
                        self.ensure_table(model)
                        if verbosity >= 2:
                            print(f"  Created: {self._table_name(model)}")
                    except Exception as exc:
                        if verbosity >= 1:
                            print(f"  Warning: could not create {self._table_name(model)}: {exc}")

        return self.connection.settings_dict["TEST"].get("NAME", "test_dynamodb")

    def destroy_test_db(self, old_database_name=None, verbosity=1, keepdb=False, suffix=None):
        if keepdb:
            return
        from django.apps import apps as django_apps
        if verbosity >= 1:
            print("Dropping DynamoDB test tables...")
        for app_config in django_apps.get_app_configs():
            for model in app_config.get_models():
                if self._model_uses_this_db(model):
                    try:
                        self.delete_table(model)
                    except Exception:
                        pass

    def _model_uses_this_db(self, model) -> bool:
        """Return True if this model is routed to the dynamodb connection."""
        from django.db import router
        try:
            return router.db_for_read(model) == self.connection.alias
        except Exception:
            return False
