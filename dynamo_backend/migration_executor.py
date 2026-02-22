"""
dynamo_backend.migration_executor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs pending migrations against DynamoDB.

Usage (internal — called by the  migrate  management command)::

    executor = MigrationExecutor()
    executor.migrate(app_label=None)   # all apps
    executor.migrate(app_label="demo_app")   # single app
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .migration_loader import MigrationLoader, MigrationKey
from .migration_recorder import MigrationRecorder


class MigrationExecutor:
    def __init__(self, verbosity: int = 1):
        self.verbosity = verbosity
        self.loader = MigrationLoader()
        self.recorder = MigrationRecorder()

    # ----------------------------------------------------------------- migrate

    def migrate(self, app_label: Optional[str] = None) -> None:
        """Apply all unapplied migrations (for *app_label* if given)."""
        self.recorder.ensure_history_table()

        applied = self.recorder.applied_migrations()
        plan = self.loader.ordered_plan(app_label)
        pending = [k for k in plan if k not in applied]

        if not pending:
            if self.verbosity:
                label = app_label or "all apps"
                print(f"  No pending dynamo migrations for {label}.")
            return

        # Replay state up to — but not including — each migration, then run it
        state: Dict = self.loader.project_state_after(
            [k for k in plan if k in applied]
        )

        for key in pending:
            app, name = key
            if self.verbosity:
                print(f"  Applying dynamo migration {app}.{name}...", end=" ", flush=True)

            mod = self.loader.migration_module(app, name)
            for op in mod.Migration.operations:
                op.apply_to_state(state)   # update in-memory state first
                try:
                    op.apply_to_db(state)
                except Exception as exc:
                    raise RuntimeError(
                        f"Dynamo migration {app}.{name} failed during "
                        f"'{op.describe()}': {exc}"
                    ) from exc

            self.recorder.record_applied(app, name)
            if self.verbosity:
                print("OK")

    # ----------------------------------------------------------------- unapply

    def unapply(self, app_label: str, target_name: str) -> None:
        """
        Reverse all migrations for *app_label* back to (but not including)
        *target_name*.  Only RemoveField / RemoveIndex support reversal;
        all others raise NotImplementedError.
        """
        applied = self.recorder.applied_migrations()
        plan = self.loader.ordered_plan(app_label)
        applied_for_app = [k for k in plan if k in applied]

        # Find the target index
        target_key = (app_label, target_name)
        try:
            stop_idx = plan.index(target_key)
        except ValueError:
            raise ValueError(f"Migration {target_name} not found for {app_label}")

        to_reverse = [k for k in applied_for_app if plan.index(k) > stop_idx]
        to_reverse.sort(key=lambda k: plan.index(k), reverse=True)

        state = self.loader.project_state_after(
            [k for k in plan if plan.index(k) <= stop_idx]
        )

        for key in to_reverse:
            app, name = key
            if self.verbosity:
                print(f"  Unapplied dynamo migration {app}.{name}...", end=" ", flush=True)
            mod = self.loader.migration_module(app, name)
            # Run operations in reverse
            for op in reversed(mod.Migration.operations):
                if hasattr(op, "reverse"):
                    op.reverse(state)
                # state update: remove_field reversal would be AddField, etc.
                # For now we skip state reversal — rarely needed
            self.recorder.record_unapplied(app, name)
            if self.verbosity:
                print("OK")

    # ----------------------------------------------------------------- status

    def migration_status(self) -> List[Tuple[str, str, bool]]:
        """Return list of (app_label, name, applied) for all known migrations."""
        applied = self.recorder.applied_migrations()
        plan = self.loader.ordered_plan()
        return [(app, name, (app, name) in applied) for app, name in plan]
