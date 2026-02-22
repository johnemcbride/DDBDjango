"""
management command:  python manage.py dmigrate [app_label]

Applies pending dynamo migrations to DynamoDB.

Examples
--------
    python manage.py dmigrate
    python manage.py dmigrate demo_app
    python manage.py dmigrate --list      # show migration status
    python manage.py dmigrate --fake      # mark as applied without running
"""

from __future__ import annotations

import sys
from typing import Optional

from django.core.management.base import BaseCommand, CommandError

from dynamo_backend.migration_executor import MigrationExecutor
from dynamo_backend.migration_loader import MigrationLoader
from dynamo_backend.migration_recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Apply pending dynamo migrations to DynamoDB."

    def add_arguments(self, parser):
        parser.add_argument(
            "app_label",
            nargs="?",
            default=None,
            help="Optional app label to migrate (default: all apps).",
        )
        parser.add_argument(
            "--list", "-l",
            action="store_true",
            help="List migration status without applying anything.",
        )
        parser.add_argument(
            "--fake",
            action="store_true",
            help="Mark migrations as applied without running them.",
        )

    def handle(self, *args, **options):
        app_label: Optional[str] = options.get("app_label")
        show_list: bool = options["list"]
        fake: bool = options["fake"]
        verbosity: int = options["verbosity"]

        executor = MigrationExecutor(verbosity=verbosity)

        if show_list:
            self._print_status(executor)
            return

        if fake:
            self._fake_migrations(executor, app_label)
            return

        executor.migrate(app_label=app_label)

    # ────────────────────────────────────────────── helpers

    def _print_status(self, executor: MigrationExecutor) -> None:
        rows = executor.migration_status()
        if not rows:
            self.stdout.write("  No dynamo migrations found.")
            return
        for app, name, applied in rows:
            tick = self.style.SUCCESS("[X]") if applied else "[ ]"
            self.stdout.write(f"  {tick} {app}.{name}")

    def _fake_migrations(
        self, executor: MigrationExecutor, app_label: Optional[str]
    ) -> None:
        recorder = MigrationRecorder()
        recorder.ensure_history_table()
        applied = recorder.applied_migrations()
        loader = MigrationLoader()
        plan = loader.ordered_plan(app_label)
        pending = [k for k in plan if k not in applied]
        if not pending:
            self.stdout.write("  No pending dynamo migrations to fake.")
            return
        for app, name in pending:
            recorder.record_applied(app, name)
            self.stdout.write(f"  Faked dynamo migration {app}.{name}")
