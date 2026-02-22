"""
dynamo_backend.migration_ops
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Operation classes used inside migration files.

Each operation knows how to:
  1. mutate the in-memory migration state  (apply_to_state)
  2. actually change DynamoDB              (apply_to_db)

Supported operations
--------------------
CreateTable   – create a DynamoDB table for a new model
AddField      – add a field to an existing table + backfill existing items
RemoveField   – remove a field from state (DynamoDB is schemaless; no DB change)
AlterField    – update field definition in state (type/default changes don't need a DB op)
AddIndex      – create a new GSI
RemoveIndex   – delete a GSI
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError


# ──────────────────────────────────────────────────────────── state helpers

ModelState = Dict[str, Any]   # {"table_name": ..., "fields": {name: field_dict}}
ProjectState = Dict[str, ModelState]  # keyed by "app_label.ModelName"


# ──────────────────────────────────────────────────────────── base class

class Operation:
    def apply_to_state(self, state: ProjectState) -> None:
        raise NotImplementedError

    def apply_to_db(self, state: ProjectState) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        return repr(self)


# ──────────────────────────────────────────────────────────── CreateTable

class CreateTable(Operation):
    def __init__(
        self,
        app_label: str,
        model_name: str,
        table_name: str,
        fields: List[Tuple[str, Any]],   # list of (field_name, Field instance)
    ):
        self.app_label = app_label
        self.model_name = model_name
        self.table_name = table_name
        self.fields = fields   # stored as field instances during apply, dicts in state

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        from .migration_fields import field_to_dict
        state[self._key()] = {
            "table_name": self.table_name,
            "fields": {name: field_to_dict(f) for name, f in self.fields},
        }

    def apply_to_db(self, state: ProjectState) -> None:
        from .connection import get_client, table_name as prefixed
        from .migration_fields import dict_to_field

        name = prefixed(self.table_name)
        client = get_client()

        field_dicts = state[self._key()]["fields"]
        index_fields = [
            (fname, dict_to_field(fd))
            for fname, fd in field_dicts.items()
            if fd.get("index") and not fd.get("primary_key")
        ]

        attr_defs = [{"AttributeName": "pk", "AttributeType": "S"}]
        key_schema = [{"AttributeName": "pk", "KeyType": "HASH"}]
        gsis = []

        for fname, field in index_fields:
            attr_defs.append({"AttributeName": fname, "AttributeType": "S"})
            gsis.append({
                "IndexName": f"{fname}-index",
                "KeySchema": [{"AttributeName": fname, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            })

        kwargs: Dict[str, Any] = {
            "TableName": name,
            "AttributeDefinitions": attr_defs,
            "KeySchema": key_schema,
            "BillingMode": "PAY_PER_REQUEST",
        }
        if gsis:
            kwargs["GlobalSecondaryIndexes"] = gsis

        try:
            client.create_table(**kwargs)
            _wait_active(client, name)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise

    def describe(self) -> str:
        return f"Create table for {self.app_label}.{self.model_name} ({self.table_name})"


# ──────────────────────────────────────────────────────────── AddField

class AddField(Operation):
    def __init__(self, app_label: str, model_name: str, field_name: str, field: Any):
        self.app_label = app_label
        self.model_name = model_name
        self.field_name = field_name
        self.field = field   # Field instance

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        from .migration_fields import field_to_dict
        state[self._key()]["fields"][self.field_name] = field_to_dict(self.field)

    def apply_to_db(self, state: ProjectState) -> None:
        """Backfill every existing item that is missing this field."""
        from .connection import get_resource, table_name as prefixed

        model_state = state[self._key()]
        table_name = prefixed(model_state["table_name"])
        table = get_resource().Table(table_name)

        default = self.field.get_default()
        if default is None:
            # Nothing to backfill — field is nullable with no default
            return

        dynamo_default = self.field.to_dynamo(default)
        if dynamo_default is None:
            return

        # Scan for items missing the attribute and update them in batches
        scan_kwargs: Dict[str, Any] = {
            "FilterExpression": "attribute_not_exists(#fn)",
            "ExpressionAttributeNames": {"#fn": self.field_name},
            "ProjectionExpression": "pk",
        }
        updated = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get("Items", [])
            for item in items:
                table.update_item(
                    Key={"pk": item["pk"]},
                    UpdateExpression="SET #fn = :val",
                    ExpressionAttributeNames={"#fn": self.field_name},
                    ExpressionAttributeValues={":val": dynamo_default},
                    ConditionExpression="attribute_not_exists(#fn)",
                )
                updated += 1
            last = response.get("LastEvaluatedKey")
            if not last:
                break
            scan_kwargs["ExclusiveStartKey"] = last

        if updated:
            print(f"    Backfilled '{self.field_name}' on {updated} existing item(s) "
                  f"in '{table_name}'.")

    def describe(self) -> str:
        return (f"Add field '{self.field_name}' to "
                f"{self.app_label}.{self.model_name} (backfill default)")


# ──────────────────────────────────────────────────────────── RemoveField

class RemoveField(Operation):
    def __init__(self, app_label: str, model_name: str, field_name: str):
        self.app_label = app_label
        self.model_name = model_name
        self.field_name = field_name

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        state[self._key()]["fields"].pop(self.field_name, None)

    def apply_to_db(self, state: ProjectState) -> None:
        # DynamoDB is schemaless — no DB change needed.
        # Items that still have the attribute are harmlessly ignored on read
        # because the field no longer exists on the model.
        pass

    def describe(self) -> str:
        return (f"Remove field '{self.field_name}' from "
                f"{self.app_label}.{self.model_name} (no DB change needed)")


# ──────────────────────────────────────────────────────────── AlterField

class AlterField(Operation):
    def __init__(self, app_label: str, model_name: str, field_name: str, field: Any):
        self.app_label = app_label
        self.model_name = model_name
        self.field_name = field_name
        self.field = field

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        from .migration_fields import field_to_dict
        state[self._key()]["fields"][self.field_name] = field_to_dict(self.field)

    def apply_to_db(self, state: ProjectState) -> None:
        # For most alterations (type, default, nullable) DynamoDB requires no
        # schema change — items store values and the Python layer interprets them.
        pass

    def describe(self) -> str:
        return f"Alter field '{self.field_name}' on {self.app_label}.{self.model_name}"


# ──────────────────────────────────────────────────────────── AddIndex

class AddIndex(Operation):
    def __init__(self, app_label: str, model_name: str, field_name: str):
        self.app_label = app_label
        self.model_name = model_name
        self.field_name = field_name

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        state[self._key()]["fields"][self.field_name]["index"] = True

    def apply_to_db(self, state: ProjectState) -> None:
        from .connection import get_client, table_name as prefixed

        model_state = state[self._key()]
        tname = prefixed(model_state["table_name"])
        client = get_client()
        index_name = f"{self.field_name}-index"

        try:
            client.update_table(
                TableName=tname,
                AttributeDefinitions=[
                    {"AttributeName": self.field_name, "AttributeType": "S"}
                ],
                GlobalSecondaryIndexUpdates=[{
                    "Create": {
                        "IndexName": index_name,
                        "KeySchema": [
                            {"AttributeName": self.field_name, "KeyType": "HASH"}
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                }],
            )
            _wait_active(client, tname)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("ResourceInUseException",):
                raise

    def describe(self) -> str:
        return (f"Add GSI index on '{self.field_name}' for "
                f"{self.app_label}.{self.model_name}")


# ──────────────────────────────────────────────────────────── RemoveIndex

class RemoveIndex(Operation):
    def __init__(self, app_label: str, model_name: str, field_name: str):
        self.app_label = app_label
        self.model_name = model_name
        self.field_name = field_name

    def _key(self) -> str:
        return f"{self.app_label}.{self.model_name}"

    def apply_to_state(self, state: ProjectState) -> None:
        if self.field_name in state[self._key()]["fields"]:
            state[self._key()]["fields"][self.field_name]["index"] = False

    def apply_to_db(self, state: ProjectState) -> None:
        from .connection import get_client, table_name as prefixed

        model_state = state[self._key()]
        tname = prefixed(model_state["table_name"])
        client = get_client()
        index_name = f"{self.field_name}-index"

        try:
            client.update_table(
                TableName=tname,
                GlobalSecondaryIndexUpdates=[{
                    "Delete": {"IndexName": index_name}
                }],
            )
            _wait_active(client, tname)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("ResourceInUseException", "ResourceNotFoundException"):
                raise

    def describe(self) -> str:
        return (f"Remove GSI index on '{self.field_name}' for "
                f"{self.app_label}.{self.model_name}")


# ──────────────────────────────────────────────────────────── helpers

def _wait_active(client, table_name: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.describe_table(TableName=table_name)
            status = resp["Table"]["TableStatus"]
            gsi_statuses = [
                g["IndexStatus"]
                for g in resp["Table"].get("GlobalSecondaryIndexes", [])
            ]
            if status == "ACTIVE" and all(s == "ACTIVE" for s in gsi_statuses):
                return
        except ClientError:
            pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for table '{table_name}' to be ACTIVE")
