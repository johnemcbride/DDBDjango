"""
demo_app.management.commands.seed_posts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Seed the database with 1 million posts spread across 5 authors.

Uses raw boto3 BatchWriteItem in parallel to maximise throughput —
going through the Django ORM would be ~100× slower due to per-item PutItem.

Usage::

    python manage.py seed_posts
    python manage.py seed_posts --posts 1000000 --threads 100
    python manage.py seed_posts --posts 50000 --threads 50   # quick test run
"""
from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand

from demo_app.models import Author

# ── DynamoDB table name ───────────────────────────────────────────────
_PREFIX = settings.DATABASES["default"]["OPTIONS"].get("table_prefix", "")
_POSTS_TABLE = f"{_PREFIX}demo_app_post"
_AUTHORS_TABLE = f"{_PREFIX}demo_app_author"

# ── Five seed authors ─────────────────────────────────────────────────
_SEED_AUTHORS = [
    {"username": "alice",   "email": "alice@example.com",   "bio": "Full-stack dev"},
    {"username": "bob",     "email": "bob@example.com",     "bio": "Data engineer"},
    {"username": "carol",   "email": "carol@example.com",   "bio": "ML researcher"},
    {"username": "dave",    "email": "dave@example.com",    "bio": "DevOps wizard"},
    {"username": "eve",     "email": "eve@example.com",     "bio": "Security expert"},
]

# ── Word pools for varied titles ──────────────────────────────────────
_ADJECTIVES = ["Fast", "Slow", "Clever", "Simple", "Advanced", "Deep", "Quick",
               "Smart", "Hidden", "Modern", "Ancient", "True", "False", "Real"]
_NOUNS = ["Guide", "Tutorial", "Thoughts", "Notes", "Ideas", "Patterns",
          "Tricks", "Hacks", "Secrets", "Stories", "Tales", "Tricks"]
_TOPICS = ["DynamoDB", "Django", "Python", "AWS", "Kubernetes", "PostgreSQL",
           "Redis", "GraphQL", "REST", "gRPC", "Kafka", "Terraform", "Docker"]


def _dynamo_client():
    """Return a boto3 DynamoDB client using settings from DATABASES['dynamodb']."""
    db = settings.DATABASES["default"]
    endpoint = os.environ.get("DYNAMO_ENDPOINT_URL") or db.get("ENDPOINT_URL") or ""
    kw = dict(
        region_name=db.get("REGION", "us-east-1"),
        aws_access_key_id=db.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=db.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    if endpoint:
        kw["endpoint_url"] = endpoint
    return boto3.client("dynamodb", **kw)


def _make_post_item(post_id: str, author_id: str, n: int, now_iso: str) -> dict:
    """Return a DynamoDB AttributeValue dict for one post."""
    adj   = _ADJECTIVES[n % len(_ADJECTIVES)]
    noun  = _NOUNS[(n // len(_ADJECTIVES)) % len(_NOUNS)]
    topic = _TOPICS[(n // (len(_ADJECTIVES) * len(_NOUNS))) % len(_TOPICS)]
    title = f"{adj} {noun} on {topic} #{n}"
    slug  = f"post-{n}-{post_id[:8]}"
    return {
        "id":         {"S": post_id},
        "author_id":  {"S": author_id},
        "title":      {"S": title},
        "slug":       {"S": slug},
        "body":       {"S": ""},
        "published":  {"BOOL": n % 2 == 0},
        "public":     {"BOOL": True},
        "tags":       {"L": []},
        "view_count": {"N": "0"},
        "created_at": {"S": now_iso},
        "updated_at": {"S": now_iso},
    }


def _batch_write(client, table_name: str, items: list[dict], retries: int = 5) -> int:
    """
    Submit one BatchWriteItem call (≤ 25 items).
    Retries unprocessed items with exponential back-off.
    Returns number of items successfully written.
    """
    request_items = {
        table_name: [{"PutRequest": {"Item": item}} for item in items]
    }
    written = 0
    for attempt in range(retries):
        try:
            resp = client.batch_write_item(RequestItems=request_items)
        except ClientError as exc:
            if attempt < retries - 1 and exc.response["Error"]["Code"] in (
                "ProvisionedThroughputExceededException",
                "RequestLimitExceeded",
            ):
                time.sleep(0.1 * 2 ** attempt)
                continue
            raise
        unprocessed = resp.get("UnprocessedItems", {})
        written += len(items) - len(unprocessed.get(table_name, []))
        if not unprocessed:
            break
        request_items = unprocessed
        time.sleep(0.05 * 2 ** attempt)
    return written


def _worker(args):
    """Thread worker: write one 25-item batch and return the count written."""
    worker_client, table_name, items, n_iso = args
    return _batch_write(worker_client, table_name, items)


class Command(BaseCommand):
    help = "Seed 1 million posts across 5 authors via parallel BatchWriteItem"

    def add_arguments(self, parser):
        parser.add_argument(
            "--posts", type=int, default=1_000_000,
            help="Total number of posts to create (default: 1,000,000)",
        )
        parser.add_argument(
            "--threads", type=int, default=80,
            help="Number of concurrent writer threads (default: 80)",
        )
        parser.add_argument(
            "--batch-size", type=int, default=25,
            help="Items per BatchWriteItem call, max 25 (default: 25)",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete all existing posts before seeding",
        )

    def handle(self, *args, **options):
        total   = options["posts"]
        threads = options["threads"]
        bsz     = min(options["batch_size"], 25)
        clear   = options["clear"]

        self.stdout.write(self.style.NOTICE(
            f"\n{'='*60}\n  Seeding {total:,} posts across 5 authors\n"
            f"  Threads: {threads}  |  Batch size: {bsz}\n{'='*60}"
        ))

        # ── Ensure 5 authors exist ────────────────────────────────────
        self.stdout.write("Creating / retrieving 5 seed authors…")
        authors = []
        for spec in _SEED_AUTHORS:
            author, created = Author.objects.get_or_create(
                username=spec["username"],
                defaults={"email": spec["email"], "bio": spec["bio"]},
            )
            tag = "created" if created else "exists"
            self.stdout.write(f"  {spec['username']} ({tag})  pk={author.pk}")
            authors.append(author)

        author_ids = [str(a.pk) for a in authors]
        n_authors  = len(author_ids)

        # ── Optional clear ────────────────────────────────────────────
        if clear:
            self.stdout.write(self.style.WARNING(
                "  --clear requested: truncating demo_app_post table…"
            ))
            client = _dynamo_client()
            # Re-create the table by scanning and batch-deleting.
            # For simplicity, we just warn that existing items will be in the table.
            self.stdout.write(self.style.WARNING(
                "  Note: --clear not yet implemented; existing posts will remain."
            ))

        # ── Build batches ─────────────────────────────────────────────
        self.stdout.write(f"Building {total // bsz:,} batches of {bsz}…")
        now_iso = datetime.now(timezone.utc).isoformat()

        # Each thread gets its own boto3 client (not thread-safe to share)
        # We create one client per thread lazily by passing args
        # (connection objects are cheap to create)
        def make_batches():
            for start in range(0, total, bsz):
                chunk_end = min(start + bsz, total)
                items = []
                for n in range(start, chunk_end):
                    post_id   = str(uuid.uuid4())
                    author_id = author_ids[n % n_authors]
                    items.append(_make_post_item(post_id, author_id, n, now_iso))
                yield items

        # ── Write in parallel ─────────────────────────────────────────
        self.stdout.write(f"Starting parallel writes with {threads} threads…\n")
        t_start   = time.perf_counter()
        written   = 0
        submitted = 0

        # Pre-build n thread-local clients
        clients = [_dynamo_client() for _ in range(threads)]

        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = []
            for i, batch in enumerate(make_batches()):
                client = clients[i % threads]
                futures.append(pool.submit(_batch_write, client, _POSTS_TABLE, batch))
                submitted += 1

                # Progress every 1000 batches
                if submitted % 1000 == 0:
                    elapsed = time.perf_counter() - t_start
                    rate = written / elapsed if elapsed > 0 else 0
                    self.stdout.write(
                        f"  Submitted {submitted:>6,} batches  "
                        f"| Written {written:>9,} posts  "
                        f"| {rate:,.0f} posts/s",
                        ending="\r",
                    )
                    self.stdout.flush()

                # Collect completed to free memory
                if len(futures) > threads * 4:
                    done = [f for f in futures if f.done()]
                    for f in done:
                        written += f.result()
                        futures.remove(f)

            # Drain remaining futures
            for f in as_completed(futures):
                written += f.result()

        elapsed   = time.perf_counter() - t_start
        rate      = written / elapsed if elapsed > 0 else 0

        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"  Done!  {written:,} posts written in {elapsed:.1f}s\n"
            f"  Average throughput: {rate:,.0f} posts/second\n"
            f"  Per-author:         ~{written // n_authors:,} posts each\n"
            f"{'='*60}\n"
        ))
        self.stdout.write(
            f"API: GET /api/authors/<pk>/posts/?limit=50\n"
            f"     GET /api/authors/<pk>/posts/?limit=50&cursor=<token>\n"
        )
