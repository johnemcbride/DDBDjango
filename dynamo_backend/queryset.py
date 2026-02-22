"""
dynamo_backend.queryset
~~~~~~~~~~~~~~~~~~~~~~~
A Django-QuerySet-inspired API backed by DynamoDB.

Supported operations:

    .all()                     → clone returning all items (full scan)
    .filter(**kwargs)          → filter by field value
    .exclude(**kwargs)         → exclude items matching kwargs
    .get(**kwargs)             → return exactly one item
    .first()                   → first item or None
    .count()                   → number of matching items
    .order_by(field)           → in-memory sort (DynamoDB doesn't sort)
    .values(*fields)           → return list of dicts
    .delete()                  → delete all matching items

Filter operators (Django-style double-underscore):
    field=value                → exact match
    field__contains=value      → substring / list member
    field__startswith=value    → string prefix
    field__gt / __gte          → numeric greater-than
    field__lt / __lte          → numeric less-than
    field__in=[...]            → value in list
    field__isnull=True/False   → attribute exists / not

Opinionated limitation: complex joins / multi-table queries are not supported
— use DynamoDB single-table design patterns when needed.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Tuple

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from .connection import get_resource, table_name as prefixed
from .exceptions import DynamoObjectNotFound, DynamoMultipleObjectsReturned


class DynamoQuerySet:
    def __init__(self, model_cls):
        self._model = model_cls
        self._filters: List[Tuple[str, str, Any]] = []   # (field, op, value)
        self._excludes: List[Tuple[str, str, Any]] = []
        self._order_by: Optional[str] = None
        self._limit: Optional[int] = None
        self._result_cache: Optional[List] = None

    # ------------------------------------------------------------------ clone

    def _clone(self) -> "DynamoQuerySet":
        qs = DynamoQuerySet(self._model)
        qs._filters = self._filters[:]
        qs._excludes = self._excludes[:]
        qs._order_by = self._order_by
        qs._limit = self._limit
        return qs

    # ----------------------------------------------------------------- public

    def all(self) -> "DynamoQuerySet":
        return self._clone()

    def filter(self, **kwargs) -> "DynamoQuerySet":
        qs = self._clone()
        for key, value in kwargs.items():
            field, op = _parse_lookup(key)
            qs._filters.append((field, op, value))
        return qs

    def exclude(self, **kwargs) -> "DynamoQuerySet":
        qs = self._clone()
        for key, value in kwargs.items():
            field, op = _parse_lookup(key)
            qs._excludes.append((field, op, value))
        return qs

    def get(self, **kwargs) -> Any:
        if "pk" in kwargs and len(kwargs) == 1:
            return self._get_by_pk(kwargs["pk"])
        results = list(self.filter(**kwargs))
        if not results:
            raise self._model.DoesNotExist(
                f"{self._model.__name__} matching query does not exist."
            )
        if len(results) > 1:
            raise self._model.MultipleObjectsReturned(
                f"{self._model.__name__}.get() returned more than one object."
            )
        return results[0]

    def first(self) -> Optional[Any]:
        if self._result_cache is None:
            self._result_cache = self._fetch()
        return self._result_cache[0] if self._result_cache else None

    def count(self) -> int:
        if self._result_cache is None:
            self._result_cache = self._fetch()
        return len(self._result_cache)

    def order_by(self, field: str) -> "DynamoQuerySet":
        qs = self._clone()
        qs._order_by = field
        return qs

    def values(self, *fields) -> List[Dict]:
        result = []
        for obj in self:
            if fields:
                result.append({f: getattr(obj, f, None) for f in fields})
            else:
                result.append(obj.to_dict())
        return result

    def delete(self) -> int:
        count = 0
        for obj in self:
            obj.delete()
            count += 1
        return count

    # -------------------------------------------------------- iteration / fetch

    def __iter__(self) -> Iterator:
        if self._result_cache is None:
            self._result_cache = self._fetch()
        return iter(self._result_cache)

    def __len__(self) -> int:
        if self._result_cache is None:
            self._result_cache = self._fetch()
        return len(self._result_cache)

    def __getitem__(self, index):
        results = list(self)
        return results[index]

    def __bool__(self) -> bool:
        return bool(list(self))

    def _set_limit(self, n: int) -> "DynamoQuerySet":
        qs = self._clone()
        qs._limit = n
        return qs

    def _fetch(self) -> List:
        table = get_resource().Table(prefixed(self._model._meta.table_name))

        # Build FilterExpression from all _filters
        filter_expr = None
        for field, op, value in self._filters:
            expr = _build_condition(field, op, value)
            filter_expr = expr if filter_expr is None else filter_expr & expr

        for field, op, value in self._excludes:
            expr = ~_build_condition(field, op, value)
            filter_expr = expr if filter_expr is None else filter_expr & expr

        scan_kwargs: Dict[str, Any] = {}
        if filter_expr is not None:
            scan_kwargs["FilterExpression"] = filter_expr
        if self._limit:
            scan_kwargs["Limit"] = self._limit

        items = _paginate_scan(table, scan_kwargs)

        # Deserialise
        objects = [self._model._from_dynamo_item(item) for item in items]

        # In-memory sort
        if self._order_by:
            reverse = self._order_by.startswith("-")
            key = self._order_by.lstrip("-")
            objects.sort(key=lambda o: (getattr(o, key, None) is None, getattr(o, key, None)), reverse=reverse)

        return objects

    def _get_by_pk(self, pk_value: str) -> Any:
        table = get_resource().Table(prefixed(self._model._meta.table_name))
        response = table.get_item(Key={"pk": str(pk_value)})
        item = response.get("Item")
        if not item:
            raise self._model.DoesNotExist(
                f"{self._model.__name__} with pk={pk_value!r} does not exist."
            )
        return self._model._from_dynamo_item(item)


# ------------------------------------------------------------------- helpers

def _parse_lookup(key: str) -> Tuple[str, str]:
    OPERATORS = {"contains", "startswith", "gt", "gte", "lt", "lte", "in", "isnull"}
    parts = key.rsplit("__", 1)
    if len(parts) == 2 and parts[1] in OPERATORS:
        return parts[0], parts[1]
    return key, "exact"


def _build_condition(field: str, op: str, value: Any):
    attr = Attr(field)
    if op == "exact":
        return attr.eq(value)
    if op == "contains":
        return attr.contains(value)
    if op == "startswith":
        return attr.begins_with(value)
    if op == "gt":
        return attr.gt(value)
    if op == "gte":
        return attr.gte(value)
    if op == "lt":
        return attr.lt(value)
    if op == "lte":
        return attr.lte(value)
    if op == "in":
        return attr.is_in(value)
    if op == "isnull":
        return attr.not_exists() if value else attr.exists()
    raise ValueError(f"Unknown filter operator: {op!r}")


def _paginate_scan(table, kwargs: Dict) -> List[Dict]:
    """Full scan with pagination support."""
    items: List[Dict] = []
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = {**kwargs, "ExclusiveStartKey": last}
        # Remove per-page Limit after first page for correctness
        kwargs.pop("Limit", None)
    return items
