"""
dynamo_backend.router
~~~~~~~~~~~~~~~~~~~~~
Database router that directs ALL models to the 'dynamodb' database.

Every app — including Django's own auth, sessions, contenttypes, and admin —
stores its data in DynamoDB.  The 'default' database entry in settings.py is
kept as an unused in-memory fallback so Django's internals don't complain, but
no traffic is ever routed there.

Configuration
─────────────
In settings.py:

    DATABASE_ROUTERS = ['dynamo_backend.router.DynamoRouter']

No DYNAMO_APPS list is needed; every model goes to 'dynamodb'.
"""

from __future__ import annotations


class DynamoRouter:
    """Route every model's reads, writes, and migrations to 'dynamodb'."""

    def db_for_read(self, model, **hints):
        return "dynamodb"

    def db_for_write(self, model, **hints):
        return "dynamodb"

    def allow_relation(self, obj1, obj2, **hints):
        # Everything is in the same database, so all FK/M2M relations are allowed.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Schema migrations for all apps run against 'dynamodb'.
        # The 'default' (in-memory SQLite) is never migrated.
        return db == "dynamodb"
