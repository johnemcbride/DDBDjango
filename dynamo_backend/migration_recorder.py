"""
dynamo_backend.migration_recorder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tracks which migrations have been applied in a DynamoDB table
called ``_dynamo_migration_history``.

Schema
------
pk          : "<app_label>.<migration_name>"   (String, hash key)
app_label   : String
name        : String  (e.g. "0001_initial")
applied_at  : ISO-8601 String
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Set

from botocore.exceptions import ClientError

_TABLE = "_dynamo_migration_history"


def _ensure_history_table() -> None:
    from .connection import get_client
    client = get_client()
    try:
        client.create_table(
            TableName=_TABLE,
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # wait
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                r = client.describe_table(TableName=_TABLE)
                if r["Table"]["TableStatus"] == "ACTIVE":
                    break
            except ClientError:
                pass
            time.sleep(0.5)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def applied_migrations() -> Set[str]:
    """Return a set of "<app_label>.<name>" strings for all applied migrations."""
    _ensure_history_table()
    from .connection import get_resource
    table = get_resource().Table(_TABLE)
    items: list = []
    kwargs: dict = {"ProjectionExpression": "pk"}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return {item["pk"] for item in items}


def record_applied(app_label: str, name: str) -> None:
    _ensure_history_table()
    from .connection import get_resource
    table = get_resource().Table(_TABLE)
    table.put_item(Item={
        "pk": f"{app_label}.{name}",
        "app_label": app_label,
        "name": name,
        "applied_at": datetime.now(tz=timezone.utc).isoformat(),
    })


def record_unapplied(app_label: str, name: str) -> None:
    _ensure_history_table()
    from .connection import get_resource
    table = get_resource().Table(_TABLE)
    table.delete_item(Key={"pk": f"{app_label}.{name}"})


# ────────────────────────────────────────── class-based wrapper

class MigrationRecorder:
    """Thin class wrapper used by MigrationExecutor and management commands."""

    def ensure_history_table(self) -> None:
        _ensure_history_table()

    def applied_migrations(self) -> Set[tuple]:
        """Return a set of (app_label, name) tuples."""
        raw = applied_migrations()   # set of "app.name" strings
        result = set()
        for pk in raw:
            parts = pk.split(".", 1)
            if len(parts) == 2:
                result.add(tuple(parts))
        return result

    def record_applied(self, app_label: str, name: str) -> None:
        record_applied(app_label, name)

    def record_unapplied(self, app_label: str, name: str) -> None:
        record_unapplied(app_label, name)
