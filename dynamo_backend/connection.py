"""
dynamo_backend.connection
~~~~~~~~~~~~~~~~~~~~~~~~~
Manages the boto3 DynamoDB resource / client singleton.

Configuration is pulled from Django settings (or env vars as fallback):

    DYNAMO_BACKEND = {
        "ENDPOINT_URL": "http://localhost:4566",   # LocalStack / DynamoDB-local
        "REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "TABLE_PREFIX": "",          # optional prefix for all table names
        "CREATE_TABLES_ON_STARTUP": True,
    }
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config

_lock = threading.Lock()
_state: Dict[str, Any] = {}   # holds "resource", "client", "config"


def _get_django_config() -> Dict[str, Any]:
    try:
        from django.conf import settings
        return getattr(settings, "DYNAMO_BACKEND", {})
    except Exception:
        return {}


def get_config() -> Dict[str, Any]:
    cfg = _get_django_config()
    # Priority: DYNAMO_ENDPOINT_URL > AWS_ENDPOINT_URL (auto-set by LocalStack
    # in Lambda environments) > Django settings > None (real AWS).
    if "DYNAMO_ENDPOINT_URL" in os.environ:
        endpoint = os.environ["DYNAMO_ENDPOINT_URL"] or None   # empty str → None
    elif "AWS_ENDPOINT_URL" in os.environ:
        endpoint = os.environ["AWS_ENDPOINT_URL"] or None
    else:
        endpoint = cfg.get("ENDPOINT_URL") or None
    return {
        "endpoint_url": endpoint,
        "region": os.environ.get("AWS_DEFAULT_REGION") or cfg.get("REGION", "us-east-1"),
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID") or cfg.get("AWS_ACCESS_KEY_ID", "test"),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY") or cfg.get("AWS_SECRET_ACCESS_KEY", "test"),
        "table_prefix": cfg.get("TABLE_PREFIX", ""),
        "create_tables_on_startup": cfg.get("CREATE_TABLES_ON_STARTUP", True),
    }


def get_resource():
    """Return the shared boto3 DynamoDB resource."""
    with _lock:
        if "resource" not in _state:
            cfg = get_config()
            kwargs = {
                "region_name": cfg["region"],
                "aws_access_key_id": cfg["aws_access_key_id"],
                "aws_secret_access_key": cfg["aws_secret_access_key"],
                "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
            }
            if cfg["endpoint_url"]:
                kwargs["endpoint_url"] = cfg["endpoint_url"]
            _state["resource"] = boto3.resource("dynamodb", **kwargs)
        return _state["resource"]


def get_client():
    """Return the shared boto3 DynamoDB low-level client."""
    with _lock:
        if "client" not in _state:
            cfg = get_config()
            kwargs = {
                "region_name": cfg["region"],
                "aws_access_key_id": cfg["aws_access_key_id"],
                "aws_secret_access_key": cfg["aws_secret_access_key"],
            }
            if cfg["endpoint_url"]:
                kwargs["endpoint_url"] = cfg["endpoint_url"]
            _state["client"] = boto3.client("dynamodb", **kwargs)
        return _state["client"]


def reset_connection() -> None:
    """Clear cached connections (useful in tests)."""
    with _lock:
        _state.clear()


def table_name(raw: str) -> str:
    """Apply optional prefix to a raw table name."""
    prefix = get_config()["table_prefix"]
    return f"{prefix}{raw}" if prefix else raw
