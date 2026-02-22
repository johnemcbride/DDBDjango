"""
dynamo_backend.backends.dynamodb.base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Django DatabaseWrapper for DynamoDB.

This class is the entry-point that Django discovers when it reads
DATABASES['dynamodb']['ENGINE'] = 'dynamo_backend.backends.dynamodb'.

It does NOT open a traditional socket connection — it holds a boto3
DynamoDB resource and exposes it to the compilers via get_dynamodb_resource().
"""

from __future__ import annotations

import threading
from typing import Any

import boto3
from botocore.config import Config

from django.db.backends.base.base import BaseDatabaseWrapper

from .features import DatabaseFeatures
from .operations import DatabaseOperations
from .creation import DatabaseCreation
from .schema import DatabaseSchemaEditor
from .introspection import DatabaseIntrospection
from .client import DatabaseClient


# Shared boto3 resource per connection alias (thread-safe)
_resource_cache: dict[str, Any] = {}
_lock = threading.Lock()


def get_dynamodb_resource(connection):
    """Return (or create) the boto3 DynamoDB resource for this connection."""
    alias = connection.alias
    with _lock:
        if alias not in _resource_cache:
            _resource_cache[alias] = _make_resource(connection.settings_dict)
        return _resource_cache[alias]


def reset_resource_cache():
    """Clear the resource cache — used in tests to force fresh clients."""
    with _lock:
        _resource_cache.clear()


def _make_resource(settings_dict: dict):
    endpoint_url = settings_dict.get("ENDPOINT_URL") or None
    region = settings_dict.get("REGION", "us-east-1")
    access_key = settings_dict.get("AWS_ACCESS_KEY_ID", "test")
    secret_key = settings_dict.get("AWS_SECRET_ACCESS_KEY", "test")

    kwargs = {
        "region_name": region,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    return boto3.resource("dynamodb", **kwargs)


# ─────────────────────────────────────────────── Fake cursor / connection


class _FakeCursor:
    """
    A no-op cursor object.  Django's DatabaseWrapper.cursor() is called in a
    few internal places (e.g. check_constraints, schema introspection).  We
    return this stub so those paths don't crash.
    """
    rowcount = 0
    lastrowid = None

    def execute(self, sql, params=()):
        pass

    def executemany(self, sql, params=()):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, size=1):
        return []

    def close(self):
        pass

    def __iter__(self):
        return iter([])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeConnection:
    """Thin wrapper returned by get_new_connection() — no real TCP connection."""
    def close(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def cursor(self):
        return _FakeCursor()


# ───────────────────────────────────────────── DatabaseWrapper


class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = "dynamodb"
    display_name = "DynamoDB"

    # Django's BaseDatabaseWrapper looks for these CLASS-level attributes and
    # instantiates them in __init__.  Set them here, not in __init__.
    SchemaEditorClass = DatabaseSchemaEditor
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    ops_class = DatabaseOperations
    introspection_class = DatabaseIntrospection

    # Map Django's internal operator names to placeholders (unused — we bypass
    # SQL generation — but required by the base class)
    operators = {
        "exact": "= %s",
        "iexact": "= UPPER(%s)",
        "contains": "LIKE %s",
        "icontains": "LIKE UPPER(%s)",
        "regex": "REGEXP %s",
        "iregex": "REGEXP %s",
        "gt": "> %s",
        "gte": ">= %s",
        "lt": "< %s",
        "lte": "<= %s",
        "startswith": "LIKE %s",
        "endswith": "LIKE %s",
        "istartswith": "LIKE UPPER(%s)",
        "iendswith": "LIKE UPPER(%s)",
    }

    pattern_esc = ""
    pattern_ops = {
        "contains": "",
        "icontains": "",
        "startswith": "",
        "istartswith": "",
        "endswith": "",
        "iendswith": "",
    }

    def __init__(self, settings_dict, alias=None):
        super().__init__(settings_dict, alias=alias or "dynamodb")
        # Base class already sets self.features, self.ops, self.creation,
        # self.introspection, self.client via their respective _class attrs.
        self._connection = None

    # ── boto3 resource access ─────────────────────────────────────────────

    def get_dynamodb_resource(self):
        return get_dynamodb_resource(self)

    # ── BaseDatabaseWrapper required overrides ────────────────────────────

    def get_connection_params(self):
        return dict(self.settings_dict)

    def get_new_connection(self, conn_params):
        return _FakeConnection()

    def init_connection_state(self):
        pass

    def create_cursor(self, name=None):
        return _FakeCursor()

    def _set_autocommit(self, autocommit):
        pass  # DynamoDB has no transactions

    def is_usable(self):
        return True

    def close(self):
        # Don't actually close the boto3 resource — it's shared
        self._connection = None

    def ensure_connection(self):
        if self._connection is None:
            self._connection = _FakeConnection()

    # ── Savepoints/transactions (no-op) ──────────────────────────────────

    def _savepoint(self, sid):
        pass

    def _savepoint_rollback(self, sid):
        pass

    def _savepoint_commit(self, sid):
        pass

    def _rollback(self):
        pass

    def _commit(self):
        pass

    # ── Compiler lookup ───────────────────────────────────────────────────

    def get_compiler(self, *args, **kwargs):
        """Fallback — compilers are normally obtained via ops.compiler()."""
        return self.ops.compiler(*args, **kwargs)
