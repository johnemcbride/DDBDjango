"""
dynamo_backend.backends.dynamodb.introspection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Minimal DatabaseIntrospection — reports DynamoDB tables as Django tables,
and returns no column information (DynamoDB is schemaless).
"""

from __future__ import annotations

from django.db.backends.base.introspection import BaseDatabaseIntrospection


class DatabaseIntrospection(BaseDatabaseIntrospection):

    def get_table_list(self, cursor):
        """Return a list of TableInfo(name, type) for all DynamoDB tables."""
        from django.db.backends.base.introspection import TableInfo
        client = self.connection.get_dynamodb_resource().meta.client
        tables = []
        kwargs: dict = {}
        while True:
            resp = client.list_tables(**kwargs)
            for name in resp.get("TableNames", []):
                tables.append(TableInfo(name, "t"))
            last = resp.get("LastEvaluatedTableName")
            if not last:
                break
            kwargs["ExclusiveStartTableName"] = last
        return tables

    def get_table_description(self, cursor, table_name):
        """DynamoDB is schemaless — return empty description."""
        return []

    def get_relations(self, cursor, table_name):
        return {}

    def get_constraints(self, cursor, table_name):
        return {}

    def get_sequences(self, cursor, table_name, columns):
        return []

    def table_names(self, cursor=None, include_views=False):
        """Return just the table name strings."""
        return [t.name for t in self.get_table_list(cursor)]
