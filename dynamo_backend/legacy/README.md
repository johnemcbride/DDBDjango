# Legacy DynamoModel Implementation

This folder contains the old implementation where models inherited from a custom `DynamoModel` base class.

**Status:** Deprecated as of v0.1.0

## What Changed

The project now uses **standard Django models** with a transparent database backend. Instead of:

```python
from dynamo_backend import DynamoModel, CharField

class Post(DynamoModel):
    title = CharField(max_length=200)
```

You now write:

```python
from django.db import models

class Post(models.Model):
    title = models.CharField(max_length=200)
```

## Files

- **models.py** - `DynamoModel` base class
- **fields.py** - Custom field types (CharField, IntegerField, etc.)
- **manager.py** - `DynamoManager` custom manager
- **queryset.py** - `DynamoQuerySet` custom queryset  
- **admin.py** - `DynamoModelAdmin` admin integration
- **table.py** - Table creation helpers (`ensure_table`, `delete_table`)
- **migration_*.py** - Custom migration system for DynamoModel
- **dmakemigrations.py** - Management command for DynamoModel migrations
- **dmigrate.py** - Management command to apply DynamoModel migrations

## Migration Guide

If you're using the old approach:

1. Change model inheritance from `DynamoModel` to `django.db.models.Model`
2. Replace custom fields with standard Django fields
3. Add `db_index=True` instead of `index=True`
4. Use standard `admin.ModelAdmin` instead of `DynamoModelAdmin`

## Backward Compatibility

These files are kept for backward compatibility but may be removed in a future major version.
