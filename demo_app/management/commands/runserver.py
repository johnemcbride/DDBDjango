"""
Override Django's built-in runserver solely to fix check_migrations().

Django's default check_migrations() is hard-coded to query
connections['default'] (our in-memory SQLite stub, intentionally never
migrated).  We override it to query the 'dynamodb' connection instead so that:

  • The warning disappears when all DynamoDB migrations are applied (correct).
  • The warning still fires if a DynamoDB migration genuinely hasn't been run.
"""
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.core.management.commands.runserver import Command as BaseRunserver


class Command(BaseRunserver):
    def check_migrations(self):
        try:
            executor = MigrationExecutor(connections["dynamodb"])
        except Exception:
            return  # LocalStack down or misconfigured — skip silently

        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            apps = sorted({m.app_label for m, _ in plan})
            self.stdout.write(
                self.style.NOTICE(
                    f"\nYou have {len(plan)} unapplied migration(s) in DynamoDB. "
                    f"Run 'python manage.py migrate --database=dynamodb' to apply them.\n"
                    f"Apps: {', '.join(apps)}"
                )
            )
