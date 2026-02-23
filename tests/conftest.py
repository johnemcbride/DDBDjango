"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared pytest fixtures.

Unit tests use moto to mock DynamoDB locally — no running AWS or LocalStack
required.  Integration tests (marked with @pytest.mark.integration) require
LocalStack to be running via docker-compose.
"""

# Set environment variables at MODULE IMPORT TIME (before any Django imports)
import pytest
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DYNAMO_SKIP_STARTUP"] = "1"
os.environ["DYNAMO_ENDPOINT_URL"] = ""  # empty → None → let moto intercept


# ──────────────────────────────────────────────────────────── moto DynamoDB

@pytest.fixture(autouse=False)
def mock_dynamodb():
    """
    Spin up an in-process mocked DynamoDB via moto.
    Each test gets a clean slate.

    Creates tables for:
      - demo_app standard Django models  (via new DatabaseCreation)
      - Any DynamoModel subclasses that fixtures request  (via old ensure_table)
    """
    from moto import mock_aws
    from django.db import connections
    from dynamo_backend.backends.dynamodb.base import reset_resource_cache
    from dynamo_backend import connection as old_conn

    # ── Patch the connection's settings_dict so the boto3 resource uses
    # endpoint_url=None (required for moto to intercept calls).  Django loads
    # settings before conftest module code, so os.environ["DYNAMO_ENDPOINT_URL"]
    # may be set too late; patching settings_dict here is the reliable approach.
    db_conn = connections["default"]
    _saved_endpoint = db_conn.settings_dict.get("ENDPOINT_URL")
    db_conn.settings_dict["ENDPOINT_URL"] = ""  # → _make_resource uses None

    # Clear any existing boto3 resource that may point at LocalStack.
    reset_resource_cache()
    old_conn.reset_connection()

    with mock_aws():
        # Create fresh resource in moto's in-memory context.
        reset_resource_cache()

        from django.apps import apps as django_apps

        # Create tables for all concrete managed models across all installed apps
        # (mirrors what DynamoBackendConfig._ensure_all_tables does on startup).
        for app_config in django_apps.get_app_configs():
            for model in app_config.get_models(include_auto_created=True):
                if model._meta.abstract or model._meta.proxy or not model._meta.managed:
                    continue
                try:
                    db_conn.creation.ensure_table(model)
                except Exception:
                    pass

        yield

        # ── Cleanup: clear caches after test ─────────────────────────────
        reset_resource_cache()
        old_conn.reset_connection()

    # Restore the original endpoint URL for non-test code (e.g. runserver).
    db_conn.settings_dict["ENDPOINT_URL"] = _saved_endpoint


# ─────────────────────────────── LocalStack (integration) fixture

@pytest.fixture(scope="session")
def localstack_dynamodb():
    """
    Assumes LocalStack is running at http://localhost:4566.
    Start it with:  docker-compose up -d
    """
    os.environ["DYNAMO_ENDPOINT_URL"] = "http://localhost:4566"

    from dynamo_backend.backends.dynamodb.base import reset_resource_cache
    reset_resource_cache()

    from django.db import connections
    db_conn = connections["default"]
    from demo_app.models import (
        Author, AuthorProfile,
        Tag,
        Category,
        Post, PostCategory,
        Comment,
        PostRevision,
    )

    _all_models = (
        Author, AuthorProfile,
        Tag,
        Category,
        Post, PostCategory,
        Comment,
        PostRevision,
        Post.labels.through,
    )

    for model in _all_models:
        try:
            db_conn.creation.delete_table(model)
        except Exception:
            pass
        db_conn.creation.ensure_table(model)

    yield

    for model in _all_models:
        try:
            db_conn.creation.delete_table(model)
        except Exception:
            pass

    os.environ.pop("DYNAMO_ENDPOINT_URL", None)
    reset_resource_cache()
