"""
dynamo_backend.migration_autodetector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compares the current DynamoModel definitions to the project state derived
from existing migration files and produces the list of Operation objects
needed to bring the migration state up to date.

Detection order (matches what Django does):
  1. New models  → CreateTable
  2. New fields  → AddField   (+ AddIndex if index=True)
  3. Removed fields → RemoveField
  4. Changed index flag → AddIndex / RemoveIndex
  5. Changed field definition → AlterField
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .migration_fields import field_to_dict
from .migration_ops import (
    CreateTable, AddField, RemoveField, AlterField, AddIndex, RemoveIndex,
    Operation,
)


def current_model_state() -> Dict:
    """
    Build the project state from the *live* DynamoModel subclasses
    (i.e. what the code says models look like right now).
    """
    from .models import _dynamo_model_registry

    state: Dict = {}
    for cls in _dynamo_model_registry:
        if cls._meta.abstract:
            continue
        key = f"{cls._meta.app_label}.{cls.__name__}"
        state[key] = {
            "table_name": cls._meta.table_name,
            "fields": {
                name: field_to_dict(field)
                for name, field in cls._meta.fields.items()
            },
        }
    return state


def detect_changes(
    migration_state: Dict,
    live_state: Dict,
    app_label: str,
) -> List[Operation]:
    """
    Compare *migration_state* (from replaying existing migration files) to
    *live_state* (from the actual model definitions) for a single *app_label*.
    Returns a list of Operation objects.
    """
    ops: List[Operation] = []

    live_keys = {k for k in live_state if k.startswith(f"{app_label}.")}
    mig_keys = {k for k in migration_state if k.startswith(f"{app_label}.")}

    # ── 1. New models → CreateTable
    for key in sorted(live_keys - mig_keys):
        model_name = key.split(".", 1)[1]
        live = live_state[key]
        from .migration_fields import dict_to_field
        fields = [
            (fname, dict_to_field(fd))
            for fname, fd in live["fields"].items()
        ]
        ops.append(CreateTable(
            app_label=app_label,
            model_name=model_name,
            table_name=live["table_name"],
            fields=fields,
        ))

    # ── 2-5. Compare fields on existing models
    for key in sorted(live_keys & mig_keys):
        model_name = key.split(".", 1)[1]
        live_fields = live_state[key]["fields"]
        mig_fields = migration_state[key]["fields"]

        live_names = set(live_fields)
        mig_names = set(mig_fields)

        from .migration_fields import dict_to_field

        # New fields
        for fname in sorted(live_names - mig_names):
            field = dict_to_field(live_fields[fname])
            ops.append(AddField(app_label, model_name, fname, field))
            # If the new field also needs an index
            if live_fields[fname].get("index"):
                ops.append(AddIndex(app_label, model_name, fname))

        # Removed fields
        for fname in sorted(mig_names - live_names):
            ops.append(RemoveField(app_label, model_name, fname))

        # Changed fields
        for fname in sorted(live_names & mig_names):
            ld = live_fields[fname]
            md = mig_fields[fname]

            # Index flag changed
            if ld.get("index") and not md.get("index"):
                ops.append(AddIndex(app_label, model_name, fname))
            elif not ld.get("index") and md.get("index"):
                ops.append(RemoveIndex(app_label, model_name, fname))

            # Field definition changed (excluding index — handled above)
            ld_no_idx = {k: v for k, v in ld.items() if k != "index"}
            md_no_idx = {k: v for k, v in md.items() if k != "index"}
            if ld_no_idx != md_no_idx:
                field = dict_to_field(live_fields[fname])
                ops.append(AlterField(app_label, model_name, fname, field))

    return ops
