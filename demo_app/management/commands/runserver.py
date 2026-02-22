"""
Override Django's built-in runserver command solely to suppress the spurious
"18 unapplied migrations" warning.

Django's runserver.check_migrations() is hard-coded to query
connections['default'] (our in-memory SQLite stub), which is intentionally
never migrated — all data lives in DynamoDB.  Setting
requires_migrations_check = False skips that check without changing any other
behaviour.
"""
from django.core.management.commands.runserver import Command as BaseRunserver


class Command(BaseRunserver):
    requires_migrations_check = False
