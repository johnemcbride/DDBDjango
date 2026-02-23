"""
dynamo_backend.migration_loader
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Discovers migration files under  <app>/dynamo_migrations/  for every
installed Django app that contains DynamoModel subclasses.

A migration file is any  ####_<name>.py  file in that directory.
It must contain a class  Migration  with:
    dependencies : list of (app_label, migration_name) tuples
    operations   : list of Operation instances
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from django.apps import apps as django_apps

# (app_label, migration_name) → module
MigrationKey = Tuple[str, str]


class MigrationLoader:
    def __init__(self):
        self._modules: Dict[MigrationKey, object] = {}   # keyed (app_label, name)
        self._graph: Dict[MigrationKey, List[MigrationKey]] = {}
        self._load_all()

    # ----------------------------------------------------------------- loading

    def _load_all(self) -> None:
        for app_config in django_apps.get_app_configs():
            mig_dir = os.path.join(app_config.path, "dynamo_migrations")
            if not os.path.isdir(mig_dir):
                continue
            for fname in sorted(os.listdir(mig_dir)):
                m = re.match(r"^(\d{4}_[\w]+)\.py$", fname)
                if not m or fname == "__init__.py":
                    continue
                name = m.group(1)
                key = (app_config.label, name)
                mod_path = f"{app_config.name}.dynamo_migrations.{name}"
                try:
                    mod = importlib.import_module(mod_path)
                    self._modules[key] = mod
                except ImportError as e:
                    raise ImportError(
                        f"Could not import dynamo migration {mod_path}: {e}"
                    ) from e

        # Build dependency graph
        for key, mod in self._modules.items():
            deps = getattr(mod.Migration, "dependencies", [])
            self._graph[key] = [tuple(d) for d in deps]

    # ----------------------------------------------------------------- queries

    def all_migrations(self) -> List[MigrationKey]:
        return list(self._modules.keys())

    def migration_module(self, app_label: str, name: str) -> object:
        return self._modules[(app_label, name)]

    def leaf_migrations(self, app_label: str) -> List[str]:
        """Return the latest (leaf) migration name(s) for an app — usually one."""
        all_for_app = [k for k in self._modules if k[0] == app_label]
        depended_upon = {
            dep
            for deps in self._graph.values()
            for dep in deps
            if dep[0] == app_label
        }
        leaves = [k for k in all_for_app if k not in depended_upon]
        return [k[1] for k in sorted(leaves)]

    def next_number(self, app_label: str) -> str:
        """Return the next zero-padded migration number for app_label, e.g. '0003'."""
        nums = [
            int(k[1].split("_")[0])
            for k in self._modules
            if k[0] == app_label
        ]
        return str((max(nums) + 1) if nums else 1).zfill(4)

    def ordered_plan(self, app_label: Optional[str] = None) -> List[MigrationKey]:
        """Topological sort of all (or one app's) migrations."""
        keys = (
            [k for k in self._modules if k[0] == app_label]
            if app_label
            else list(self._modules.keys())
        )
        visited: set = set()
        result: List[MigrationKey] = []

        def visit(key: MigrationKey) -> None:
            if key in visited:
                return
            visited.add(key)
            for dep in self._graph.get(key, []):
                if dep in self._modules:
                    visit(dep)
            result.append(key)

        for k in keys:
            visit(k)
        return result

    def project_state_after(
        self, keys: Optional[List[MigrationKey]] = None
    ) -> Dict:
        """
        Replay operations up to (and including) *keys* to compute the
        accumulated project state.  If *keys* is None, replay everything.
        """
        state: Dict = {}
        plan = self.ordered_plan()
        for key in plan:
            if keys is not None and key not in keys:
                continue
            mod = self._modules[key]
            for op in mod.Migration.operations:
                op.apply_to_state(state)
        return state
