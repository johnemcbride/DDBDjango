"""
dynamo_backend.router
~~~~~~~~~~~~~~~~~~~~~
Database router that directs models whose app_label is listed in
settings.DYNAMO_APPS to the 'dynamodb' database connection, and routes
everything else to Django's 'default' connection.

Configuration
─────────────
In settings.py:

    DATABASE_ROUTERS = ['dynamo_backend.router.DynamoRouter']
    DYNAMO_APPS = ['demo_app']          # list of app labels to route to DynamoDB

Django auth / admin / session models keep using 'default' (SQLite) so
Django's own machinery keeps working without modification.
"""

from __future__ import annotations

from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=None)
def _dynamo_apps() -> frozenset:
    return frozenset(getattr(settings, "DYNAMO_APPS", []))


class DynamoRouter:
    """
    Route reads / writes / migrations for DYNAMO_APPS to the 'dynamodb'
    database, and block cross-database relations.
    """

    @staticmethod
    def _is_dynamo(app_label: str) -> bool:
        return app_label in _dynamo_apps()

    def db_for_read(self, model, **hints):
        if self._is_dynamo(model._meta.app_label):
            return "dynamodb"
        return None

    def db_for_write(self, model, **hints):
        if self._is_dynamo(model._meta.app_label):
            return "dynamodb"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations only within the same database tier (both DynamoDB or
        both relational).  Prevent cross-DB FK relations.
        """
        obj1_dynamo = self._is_dynamo(obj1._meta.app_label)
        obj2_dynamo = self._is_dynamo(obj2._meta.app_label)
        if obj1_dynamo == obj2_dynamo:
            return True
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        DynamoDB app label migrations run only on the 'dynamodb' connection.
        Django internal app migrations run only on 'default'.
        """
        if self._is_dynamo(app_label):
            return db == "dynamodb"
        # Let other apps use their own db (typically 'default')
        if db == "dynamodb":
            return False
        return None
