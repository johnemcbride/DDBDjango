"""
dynamo_backend.exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~
Custom exceptions for the DynamoDB backend.
"""


class DynamoObjectNotFound(Exception):
    """Raised when a requested object does not exist in DynamoDB."""
    pass


class DynamoMultipleObjectsReturned(Exception):
    """Raised when get() finds more than one result."""
    pass


class DynamoValidationError(Exception):
    """Raised when field validation fails."""
    pass


class DynamoTableError(Exception):
    """Raised on table creation / schema errors."""
    pass
