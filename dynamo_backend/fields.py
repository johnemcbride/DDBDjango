"""
dynamo_backend.fields
~~~~~~~~~~~~~~~~~~~~~
Field descriptors for DynamoModel.

Each field knows how to:
  - Validate a Python value
  - Serialise to a DynamoDB-compatible value (str / Decimal / bool / list / dict)
  - Deserialise from DynamoDB back to Python

Design decision: all numbers are stored as Decimal in DynamoDB (the SDK
requirement), but returned as int/float on the Python side.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .exceptions import DynamoValidationError


class Field:
    """Base field class."""

    # ── Django ORM compatibility attributes ──────────────────────────────
    # django.contrib.admin (and other Django internals) inspect these on
    # every field object returned by Options.get_field() / opts.fields.
    # DynamoDB fields are never ORM relations, so all relation flags are
    # False/None.  attname mirrors the field name (set in contribute_to_class).
    remote_field = None
    is_relation = False
    many_to_many = False
    many_to_one = False
    one_to_many = False
    one_to_one = False
    related_model = None
    column = None
    auto_created = False
    editable = True
    hidden = False
    concrete = True
    unique = False
    null = True       # DynamoDB fields are nullable by default
    attname: str = ""  # set in contribute_to_class
    # Django admin display/form compat
    empty_values = list((None, "", [], (), {}))
    flatchoices: list = []
    choices: list = []
    help_text: str = ""
    model = None
    encoder = None       # JSONField compat
    decimal_places = None  # DecimalField compat

    def related_query_name(self) -> str:
        return ""

    def __init__(
        self,
        *,
        primary_key: bool = False,
        index: bool = False,
        nullable: bool = True,
        default: Any = None,
    ):
        self.primary_key = primary_key
        self.index = index          # creates a GSI on this attribute
        self.nullable = nullable
        self._default = default
        self.name: str = ""         # set by DynamoModelMetaclass
        self.verbose_name: str = "" # set in contribute_to_class
        # pk fields are always unique and non-null
        if primary_key:
            self.unique = True
            self.null = False

    def get_default(self) -> Any:
        if callable(self._default):
            return self._default()
        return self._default

    def validate(self, value: Any) -> None:
        if not self.nullable and value is None:
            raise DynamoValidationError(f"Field '{self.name}' cannot be None")

    def to_dynamo(self, value: Any) -> Any:
        """Serialise Python → DynamoDB item attribute value."""
        return value

    def from_dynamo(self, value: Any) -> Any:
        """Deserialise DynamoDB attribute value → Python."""
        return value

    def contribute_to_class(self, cls, name: str) -> None:
        self.name = name
        self.attname = name
        self.verbose_name = name.replace("_", " ")
        cls._meta.fields[name] = self


class CharField(Field):
    def __init__(self, *, max_length: int = 255, **kwargs):
        super().__init__(**kwargs)
        self.max_length = max_length

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, str):
            raise DynamoValidationError(
                f"CharField '{self.name}' requires a str, got {type(value).__name__}"
            )
        if value and self.max_length and len(value) > self.max_length:
            raise DynamoValidationError(
                f"CharField '{self.name}' exceeds max_length={self.max_length}"
            )

    def to_dynamo(self, value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    def from_dynamo(self, value: Any) -> Optional[str]:
        return str(value) if value is not None else None


class IntegerField(Field):
    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, (int, Decimal)):
            raise DynamoValidationError(
                f"IntegerField '{self.name}' requires an int, got {type(value).__name__}"
            )

    def to_dynamo(self, value: Any) -> Optional[Decimal]:
        return Decimal(int(value)) if value is not None else None

    def from_dynamo(self, value: Any) -> Optional[int]:
        return int(value) if value is not None else None


class FloatField(Field):
    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, (int, float, Decimal)):
            raise DynamoValidationError(
                f"FloatField '{self.name}' requires a number, got {type(value).__name__}"
            )

    def to_dynamo(self, value: Any) -> Optional[Decimal]:
        return Decimal(str(value)) if value is not None else None

    def from_dynamo(self, value: Any) -> Optional[float]:
        return float(value) if value is not None else None


class BooleanField(Field):
    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, bool):
            raise DynamoValidationError(
                f"BooleanField '{self.name}' requires a bool, got {type(value).__name__}"
            )

    def to_dynamo(self, value: Any) -> Optional[bool]:
        return bool(value) if value is not None else None

    def from_dynamo(self, value: Any) -> Optional[bool]:
        return bool(value) if value is not None else None


class DateTimeField(Field):
    """Stored as ISO-8601 string in DynamoDB."""

    def __init__(self, *, auto_now: bool = False, auto_now_add: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add
        if auto_now_add and self._default is None:
            self._default = lambda: datetime.now(tz=timezone.utc)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, (datetime, str)):
            raise DynamoValidationError(
                f"DateTimeField '{self.name}' requires a datetime or ISO-8601 str"
            )

    def to_dynamo(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def from_dynamo(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)


class JSONField(Field):
    """Stores arbitrary dicts / lists as a DynamoDB Map or List."""

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, (dict, list)):
            raise DynamoValidationError(
                f"JSONField '{self.name}' requires a dict or list"
            )

    def to_dynamo(self, value: Any) -> Any:
        return value  # boto3 handles nested dicts/lists natively

    def from_dynamo(self, value: Any) -> Any:
        return value


class UUIDField(Field):
    """Stored as a string in DynamoDB. Auto-generates UUID4 by default."""

    def __init__(self, **kwargs):
        if "default" not in kwargs:
            kwargs["default"] = lambda: str(uuid.uuid4())
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                uuid.UUID(str(value))
            except ValueError:
                raise DynamoValidationError(
                    f"UUIDField '{self.name}' received an invalid UUID: {value!r}"
                )

    def to_dynamo(self, value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    def from_dynamo(self, value: Any) -> Optional[str]:
        return str(value) if value is not None else None


class ListField(Field):
    """Stores a list of scalars (str, int, Decimal) as a DynamoDB List."""

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, list):
            raise DynamoValidationError(
                f"ListField '{self.name}' requires a list, got {type(value).__name__}"
            )

    def to_dynamo(self, value: Any) -> Optional[list]:
        return value

    def from_dynamo(self, value: Any) -> Optional[list]:
        return value
