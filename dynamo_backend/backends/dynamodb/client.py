"""
dynamo_backend.backends.dynamodb.client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Minimal DatabaseClient stub — we don't use a command-line DB client.
"""

from django.db.backends.base.client import BaseDatabaseClient


class DatabaseClient(BaseDatabaseClient):
    executable_name = "aws"

    @classmethod
    def settings_to_cmd(cls, *args, **kwargs):
        return []
