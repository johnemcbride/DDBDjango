"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared pytest fixtures.

Unit tests use moto to mock DynamoDB locally — no running AWS or LocalStack
required.  Integration tests (marked with @pytest.mark.integration) require
LocalStack to be running via docker-compose.
"""

import os
import pytest

# ──────────────────────────────────────────────────────────────── Django setup

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Prevent DynamoBackendConfig.ready() from trying to reach AWS/LocalStack
# before our moto mock is in place.
os.environ["DYNAMO_SKIP_STARTUP"] = "1"
os.environ["DYNAMO_ENDPOINT_URL"] = ""   # empty → None → let moto intercept

import django
django.setup()


# ──────────────────────────────────────────────────────────── moto DynamoDB

@pytest.fixture(autouse=False)
def mock_dynamodb():
    """
    Spin up an in-process mocked DynamoDB via moto.
    Each test gets a clean slate.
    """
    from moto import mock_aws

    # Override endpoint BEFORE moto starts so the cached client is never created
    # with localhost:4566 (from Django settings).  Empty string → None → no override.
    os.environ["DYNAMO_ENDPOINT_URL"] = ""

    with mock_aws():
        from dynamo_backend import connection
        connection.reset_connection()   # ensure fresh boto3 clients inside moto

        from dynamo_backend.table import ensure_table
        from demo_app.models import Author, Post, Comment

        for model_cls in (Author, Post, Comment):
            ensure_table(model_cls)

        yield

        connection.reset_connection()

    os.environ.pop("DYNAMO_ENDPOINT_URL", None)


# ─────────────────────────────── LocalStack (integration) fixture

@pytest.fixture(scope="session")
def localstack_dynamodb():
    """
    Assumes LocalStack is running at http://localhost:4566.
    Start it with:  docker-compose up -d
    """
    import boto3
    from dynamo_backend import connection

    os.environ["DYNAMO_ENDPOINT_URL"] = "http://localhost:4566"
    connection.reset_connection()

    from dynamo_backend.table import ensure_table, delete_table
    from demo_app.models import Author, Post, Comment

    for model_cls in (Author, Post, Comment):
        try:
            delete_table(model_cls)
        except Exception:
            pass
        ensure_table(model_cls)

    yield

    for model_cls in (Author, Post, Comment):
        try:
            delete_table(model_cls)
        except Exception:
            pass

    os.environ.pop("DYNAMO_ENDPOINT_URL", None)
    connection.reset_connection()
