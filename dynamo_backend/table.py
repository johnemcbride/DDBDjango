"""
dynamo_backend.table
~~~~~~~~~~~~~~~~~~~~
Helpers for creating, describing and ensuring DynamoDB tables exist.

Opinionated schema:
  - Every table has a single String hash key called ``pk`` (UUID by default).
  - Any field marked ``index=True`` gets a Global Secondary Index (GSI)
    with hash key = that field value and range key = ``pk``.
  - Billing: PAY_PER_REQUEST (no provisioned throughput to manage).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List

from botocore.exceptions import ClientError

from .connection import get_client, get_resource, table_name as prefixed
from .exceptions import DynamoTableError

if TYPE_CHECKING:
    from .models import DynamoModel


def ensure_table(model_cls: type) -> None:
    """Create the DynamoDB table for *model_cls* if it does not exist."""
    meta = model_cls._meta
    name = prefixed(meta.table_name)
    client = get_client()

    # Collect indexed fields (non-pk)
    index_fields = [
        f for f in meta.fields.values() if f.index and not f.primary_key
    ]

    attribute_definitions = [
        {"AttributeName": "pk", "AttributeType": "S"},
    ]
    key_schema = [{"AttributeName": "pk", "KeyType": "HASH"}]

    gsi_list = []
    for field in index_fields:
        attr_type = _dynamo_type(field)
        attribute_definitions.append(
            {"AttributeName": field.name, "AttributeType": attr_type}
        )
        gsi_list.append(
            {
                "IndexName": f"{field.name}-index",
                "KeySchema": [
                    {"AttributeName": field.name, "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        )

    create_kwargs = {
        "TableName": name,
        "AttributeDefinitions": attribute_definitions,
        "KeySchema": key_schema,
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsi_list:
        create_kwargs["GlobalSecondaryIndexes"] = gsi_list

    try:
        client.create_table(**create_kwargs)
        _wait_for_table(name)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceInUseException":
            pass  # table already exists — that's fine
        else:
            raise DynamoTableError(f"Failed to create table '{name}': {exc}") from exc


def delete_table(model_cls: type) -> None:
    """Delete the DynamoDB table for *model_cls* (used in tests)."""
    name = prefixed(model_cls._meta.table_name)
    client = get_client()
    try:
        client.delete_table(TableName=name)
        _wait_for_deleted(name)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("ResourceNotFoundException", "ResourceInUseException"):
            pass
        else:
            raise DynamoTableError(f"Failed to delete table '{name}': {exc}") from exc


def _wait_for_table(name: str, timeout: int = 30) -> None:
    client = get_client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.describe_table(TableName=name)
            if resp["Table"]["TableStatus"] == "ACTIVE":
                return
        except ClientError:
            pass
        time.sleep(0.5)
    raise DynamoTableError(f"Timed out waiting for table '{name}' to become ACTIVE")


def _wait_for_deleted(name: str, timeout: int = 30) -> None:
    client = get_client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.describe_table(TableName=name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                return
        time.sleep(0.5)


def _dynamo_type(field) -> str:
    """Return DynamoDB attribute type string for a field."""
    from .fields import IntegerField, FloatField, BooleanField
    if isinstance(field, (IntegerField, FloatField)):
        return "N"
    if isinstance(field, BooleanField):
        return "S"   # booleans stored as BOOL but GSI keys must be S or N
    return "S"
