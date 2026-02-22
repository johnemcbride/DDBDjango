"""
dynamo_backend.opensearch_sync
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Best-effort OpenSearch sync layer.

Every DynamoDB write (PUT_ITEM, UPDATE_ITEM, DELETE_ITEM) calls into this
module to keep the OpenSearch index up to date.  If OpenSearch is unavailable
the DynamoDB write still succeeds — sync failures are logged but never
propagated to the caller.

Index naming
────────────
One index per DynamoDB table, named identically to the table (lowercased,
dots/hyphens replaced with underscores to satisfy OpenSearch naming rules).

Admin search mixin
──────────────────
See ``OpenSearchAdminMixin`` in ``dynamo_backend.admin_search``.

Management command
──────────────────
    python manage.py opensearch_reindex

rebuilds every index from scratch by scanning all DynamoDB tables.
"""

from __future__ import annotations

import decimal
import logging
from typing import Sequence

from django.conf import settings

logger = logging.getLogger("dynamo_backend.opensearch_sync")


# ── client singleton ─────────────────────────────────────────────────────────

_client = None
_client_checked = False  # True once we've attempted a connection


def _get_client():
    """Return a cached OpenSearch client backed by LocalStack, or None.

    First call uses boto3 to create/describe the OpenSearch domain inside
    LocalStack, then builds an opensearch-py client pointing at the domain
    endpoint that LocalStack returns.  All errors are non-fatal.
    """
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    endpoint_url = getattr(settings, "OPENSEARCH_ENDPOINT_URL", None)
    domain_name = getattr(settings, "OPENSEARCH_DOMAIN_NAME", "ddbdjango")

    if not endpoint_url:
        logger.debug("OPENSEARCH_ENDPOINT_URL not set — search will use DDB scans")
        return None

    try:
        import boto3  # type: ignore[import]
        from opensearchpy import OpenSearch  # type: ignore[import]

        db = settings.DATABASES.get("default", {})
        region = db.get("REGION", "us-east-1")
        key_id = db.get("AWS_ACCESS_KEY_ID", "test")
        key_secret = db.get("AWS_SECRET_ACCESS_KEY", "test")

        boto_client = boto3.client(
            "opensearch",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=key_id,
            aws_secret_access_key=key_secret,
        )

        # Idempotently create the domain (LocalStack is instant; real AWS is slow)
        try:
            boto_client.create_domain(DomainName=domain_name)
            logger.info("Created LocalStack OpenSearch domain '%s'", domain_name)
        except boto_client.exceptions.ResourceAlreadyExistsException:
            pass  # already exists — that's fine
        except Exception as exc:
            # Older LocalStack versions raise a generic exception for duplicates
            if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
                raise

        # Retrieve the domain endpoint
        resp = boto_client.describe_domain(DomainName=domain_name)
        domain_status = resp["DomainStatus"]
        # LocalStack (domain strategy) returns e.g.
        #   "ddbdjango.us-east-1.opensearch.localhost.localstack.cloud:4566"
        # (path strategy) returns e.g.
        #   "localhost:4566/opensearch/us-east-1/ddbdjango"
        endpoint = domain_status.get("Endpoint") or next(
            iter(domain_status.get("Endpoints", {}).values()), None
        )

        if not endpoint:
            logger.warning(
                "LocalStack OpenSearch domain '%s' has no endpoint yet", domain_name
            )
            return None

        # Normalise: strip scheme if present
        host_str = endpoint.split("://", 1)[-1]

        # Detect path-strategy URLs (contain '/' after host:port)
        if "/" in host_str:
            host_port, path_prefix = host_str.split("/", 1)
            path_prefix = "/" + path_prefix
        else:
            host_port = host_str
            path_prefix = ""

        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 80

        # Build opensearch-py client
        kwargs: dict = dict(
            hosts=[{"host": host, "port": port}],
            use_ssl=False,
            verify_certs=False,
            timeout=10,
            max_retries=2,
            retry_on_timeout=False,
        )
        if path_prefix:
            # path strategy — pass prefix so every request is rooted correctly
            kwargs["url_prefix"] = path_prefix

        c = OpenSearch(**kwargs)
        c.info()  # quick connectivity check
        _client = c
        logger.info(
            "OpenSearch ready: LocalStack domain '%s' at %s:%s%s",
            domain_name, host, port, path_prefix,
        )
    except Exception as exc:
        logger.warning(
            "OpenSearch unavailable (%s) — search will fall back to DDB scans", exc
        )
        _client = None

    return _client


def reset_client() -> None:
    """Force a reconnect attempt on the next call (used in tests)."""
    global _client, _client_checked
    _client = None
    _client_checked = False


# ── index helpers ─────────────────────────────────────────────────────────────

_known_indices: set[str] = set()


def _index_name(table_name: str) -> str:
    """Map a DynamoDB table name to an OpenSearch index name."""
    return table_name.lower().replace(".", "_").replace("-", "_")


def ensure_index(table_name: str) -> bool:
    """Create the OpenSearch index for *table_name* if it doesn't exist yet.

    Returns True if the index is ready, False if OS is unavailable.
    """
    client = _get_client()
    if client is None:
        return False

    idx = _index_name(table_name)
    if idx in _known_indices:
        return True

    try:
        if not client.indices.exists(index=idx):
            client.indices.create(
                index=idx,
                body={
                    "settings": {
                        "index": {
                            "number_of_shards": 1,
                            "number_of_replicas": 0,
                        }
                    },
                    "mappings": {
                        # dynamic mapping — OS infers field types automatically
                        "dynamic": True,
                    },
                },
            )
            logger.debug("Created OpenSearch index %s", idx)
        _known_indices.add(idx)
        return True
    except Exception as exc:
        logger.warning("ensure_index(%s) failed: %s", idx, exc)
        return False


# ── value serialisation ───────────────────────────────────────────────────────

def _safe_value(v):
    """Convert DynamoDB attribute values to JSON-serialisable types."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [_safe_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _safe_value(vv) for k, vv in v.items()}
    return v


# ── write-side sync ───────────────────────────────────────────────────────────

def index_document(table_name: str, pk: str, item: dict) -> None:
    """Index (insert or replace) a single DynamoDB item into OpenSearch."""
    if not ensure_index(table_name):
        return
    client = _get_client()
    if client is None:
        return
    try:
        doc = {k: _safe_value(v) for k, v in item.items()}
        client.index(
            index=_index_name(table_name),
            id=str(pk),
            body=doc,
            refresh="false",  # async — no performance hit on writes
        )
    except Exception as exc:
        logger.warning(
            "index_document(%s, %s) failed: %s", table_name, pk, exc
        )


def delete_document(table_name: str, pk: str) -> None:
    """Remove a single document from OpenSearch."""
    if not ensure_index(table_name):
        return
    client = _get_client()
    if client is None:
        return
    try:
        client.delete(
            index=_index_name(table_name),
            id=str(pk),
            ignore=[404],
        )
    except Exception as exc:
        logger.warning(
            "delete_document(%s, %s) failed: %s", table_name, pk, exc
        )


def delete_documents(table_name: str, pks: Sequence[str]) -> None:
    """Bulk-remove multiple documents from OpenSearch."""
    if not pks:
        return
    if not ensure_index(table_name):
        return
    client = _get_client()
    if client is None:
        return
    try:
        from opensearchpy.helpers import bulk  # type: ignore[import]

        actions = [
            {
                "_op_type": "delete",
                "_index": _index_name(table_name),
                "_id": str(pk),
            }
            for pk in pks
        ]
        bulk(client, actions, raise_on_error=False)
    except Exception as exc:
        logger.warning("delete_documents(%s) failed: %s", table_name, exc)


# ── read-side search ──────────────────────────────────────────────────────────

def search_pks(
    table_name: str,
    query: str,
    fields: Sequence[str],
    limit: int = 1000,
) -> list[str] | None:
    """Full-text search across *fields* for *query*.

    Returns a (possibly empty) list of PK strings when OpenSearch is available,
    or ``None`` to signal "fall back to DDB scan-based search".

    The query uses a ``bool/should`` combination of:
    - ``multi_match`` (best_fields, fuzziness=AUTO) — finds whole-word matches
      and handles typos.
    - ``query_string`` with leading/trailing wildcards — handles substring
      matches like ``icontains``.
    Both are OR-ed together so a partial word match is still promoted.
    """
    client = _get_client()
    if client is None:
        return None
    if not ensure_index(table_name):
        return None

    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    field_list = list(fields)

    body: dict = {
        "size": limit,
        "_source": False,  # only need doc IDs
        "query": {
            "bool": {
                "should": [
                    # Tokenised match — handles whole words, auto-fuzziness
                    {
                        "multi_match": {
                            "query": query,
                            "fields": field_list,
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                            "operator": "or",
                        }
                    },
                    # Wildcard substring match — mimics icontains behaviour
                    {
                        "query_string": {
                            "query": f"*{escaped}*",
                            "fields": field_list,
                            "default_operator": "OR",
                            "analyze_wildcard": True,
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        },
    }

    try:
        resp = client.search(index=_index_name(table_name), body=body)
        return [hit["_id"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        logger.warning(
            "search_pks(%s, %r) failed: %s — falling back to DDB scan",
            table_name,
            query,
            exc,
        )
        return None
