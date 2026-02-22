"""
dynamo_backend.backends.dynamodb.operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DatabaseOperations for DynamoDB.

Provides the handful of helpers Django calls to adapt values and quote names.
Most SQL-specific operations are no-ops or raise NotImplementedError since
we bypass SQL generation entirely in our compilers.
"""

from django.db.backends.base.operations import BaseDatabaseOperations


class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = "dynamo_backend.backends.dynamodb.compiler"

    def quote_name(self, name):
        """DynamoDB names don't need quoting."""
        return name

    def last_insert_id(self, cursor, table_name, pk_name):
        """
        Return the last inserted PK.  Our InsertCompiler sets cursor.lastrowid
        to the newly generated/used PK value.
        """
        return cursor.lastrowid

    def adapt_datetimefield_value(self, value):
        """Store datetimes as ISO-8601 strings."""
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def adapt_datefield_value(self, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def adapt_timefield_value(self, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def adapt_decimalfield_value(self, value, max_digits=None, decimal_places=None):
        if value is None:
            return None
        from decimal import Decimal
        return Decimal(str(value))

    def adapt_unknown_value(self, value):
        return value

    def no_limit_value(self):
        return None

    def limit_offset_sql(self, low_mark, high_mark):
        raise NotImplementedError("DynamoDB doesn't use SQL LIMIT/OFFSET")

    def for_update_sql(self, nowait=False, skip_locked=False, of=(), no_key=False):
        raise NotImplementedError("DynamoDB doesn't support SELECT FOR UPDATE")

    def return_insert_columns(self, fields):
        return [], []

    def bulk_insert_sql(self, fields, placeholder_rows):
        raise NotImplementedError("DynamoDB doesn't use SQL bulk insert")

    def fetch_returned_insert_columns(self, cursor, query):
        return (cursor.lastrowid,)

    def get_db_converters(self, expression):
        converters = super().get_db_converters(expression)
        return converters

    def integer_field_range(self, *args, **kwargs):
        # DynamoDB numbers are arbitrary precision
        return (None, None)

    def max_name_length(self):
        return 255

    def sql_flush(self, style, tables, *, reset_sequences=False, allow_cascade=False):
        # Our schema editor will handle truncation via DynamoDB calls
        return ["DYNAMO_FLUSH:{}".format(t) for t in tables]

    def execute_sql_flush(self, sql_list):
        # Each "sql" is actually "DYNAMO_FLUSH:<table>"
        import boto3
        from .base import get_dynamodb_resource
        dynamodb = get_dynamodb_resource(self.connection)
        for item in sql_list:
            if item.startswith("DYNAMO_FLUSH:"):
                table_name = item[len("DYNAMO_FLUSH:"):]
                self._flush_table(dynamodb, table_name)

    def _flush_table(self, dynamodb, table_name):
        """Delete all items in a DynamoDB table (used for test flushing)."""
        try:
            table = dynamodb.Table(table_name)
            table_desc = table.meta.client.describe_table(TableName=table_name)
            key_schema = table_desc["Table"]["KeySchema"]
            key_attrs = [k["AttributeName"] for k in key_schema]

            scan_kwargs = {"ProjectionExpression": ", ".join(key_attrs)}
            while True:
                resp = table.scan(**scan_kwargs)
                items = resp.get("Items", [])
                if not items:
                    break
                with table.batch_writer() as batch:
                    for item in items:
                        batch.delete_item(Key={k: item[k] for k in key_attrs})
                if "LastEvaluatedKey" not in resp:
                    break
                scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        except Exception:
            pass
