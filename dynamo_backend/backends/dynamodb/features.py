"""
dynamo_backend.backends.dynamodb.features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DatabaseFeatures for DynamoDB — mostly a "no SQL features" implementation.
"""

from django.db.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    # DynamoDB is not a relational database
    supports_transactions = False
    supports_foreign_keys = False
    can_return_rows_from_bulk_insert = False
    can_return_columns_from_insert = True   # we generate the pk and return it
    supports_select_for_update = False
    supports_select_related = False
    has_select_for_update = False
    has_select_for_update_nowait = False
    has_select_for_update_skip_locked = False
    supports_subqueries_in_group_by = False
    supports_column_check_constraints = False
    supports_table_check_constraints = False
    can_introspect_check_constraints = False
    supports_paramstyle_pyformat = False
    supports_sequence_reset = False
    can_defer_constraint_checks = False
    supports_regex_backreferences = False
    supports_timezones = False
    has_zoneinfo_database = False
    supports_over_clause = False
    order_by_nulls_first = False
    allows_group_by_pk = False
    # We handle NULL checks ourselves
    interprets_empty_strings_as_nulls = False
    # DynamoDB is essentially always "available"
    uses_savepoints = False
    can_release_savepoints = False
    # aggregation is only COUNT (done via Scan)
    supports_aggregate_filter_clause = False
    supports_expression_indexes = False
    supports_index_on_expressions = False
    # No SQL migrations needed — schema is managed via create_model/delete_model
    supports_migrations = True
    # Allow empty QuerySets from .none()
    supports_empty_in = True
    # Let Django generate PKs (UUID)
    has_native_uuid_field = False
