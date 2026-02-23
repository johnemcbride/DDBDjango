# DDBDjango

A Django application with a **DynamoDB backend** and **OpenSearch integration** — no relational DB required.

## What's in the box

| Path | Purpose |
|---|---|
| `dynamo_backend/` | The DynamoDB backend library with OpenSearch sync |
| `demo_app/` | Full-featured blog demo with frontend templates |
| `config/` | Django project settings & routing |
| `tests/` | Unit + view test suite (moto) |
| `docker-compose.yml` | LocalStack + OpenSearch for local development |

## ✨ Features

- 🗄️ **DynamoDB Backend** - Use DynamoDB as your primary database
- 🔍 **OpenSearch Integration** - Automatic syncing with full-text search
- 🔐 **AWS Cognito Auth** - User authentication via Cognito (with mock support)
- 🗂️ **Django Migrations** - Custom migration system for DynamoDB
- 🎨 **Admin Panel** - Django admin with DynamoDB search capabilities
- 📝 **Blog Demo** - Complete blog with authors, posts, comments, tags, and categories
- 🧪 **Testing Suite** - Comprehensive tests with moto mocking

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Django App                        │
│  views.py  ──►  models.py (DynamoModel subclasses)  │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               dynamo_backend library                  │
│                                                       │
│  DynamoModel ──► DynamoManager ──► DynamoQuerySet    │
│       │              │                     │          │
│   fields.py    opensearch_sync.py   connection.py   │
│   table.py          │              (boto3 resource) │
└───────┬─────────────┼──────────────┬────────────────┘
        │             │              │
        │             └──────────┐   │
        │                        │   │
┌───────▼────────────┐  ┌────────▼───▼────────┐
│  OpenSearch        │  │   AWS DynamoDB      │
│  (full-text search)│  │  (or LocalStack)    │
└────────────────────┘  └─────────────────────┘
```

### Opinionated design decisions

* **No Django ORM** — `DynamoModel` bypasses `django.db.models.Model` entirely.
* **UUID primary keys** — every table has a `pk` string attribute (UUID4).
* **PAY_PER_REQUEST billing** — no capacity planning needed.
* **GSI per indexed field** — mark a field `index=True` to get a Global Secondary Index for `filter()`.
* **No JOINs** — foreign-key relations are stored as `<model>_pk` string fields.
* **Auto table creation** — tables are created on Django startup (configurable).

---

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start LocalStack

```bash
docker-compose up -d
# Wait for: "localstack_1 | Ready."
```

### 3. Run the development server

```bash
python manage.py runserver
```

Tables are created automatically on first startup.

### 4. Try the application

**Web Interface:**
- Homepage: http://localhost:8000/
- Post Explorer: http://localhost:8000/explorer/
- Write Post: http://localhost:8000/write/
- Admin Panel: http://localhost:8000/admin/

**REST API:**

```bash
# Create an author
curl -s -X POST http://localhost:8000/api/authors/ \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@example.com","bio":"Writer"}' | python -m json.tool

# Create a post
curl -s -X POST http://localhost:8000/api/posts/ \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello DynamoDB","slug":"hello-dynamodb","author_pk":"<author-pk>","published":true}' | python -m json.tool

# List posts
curl -s http://localhost:8000/api/posts/ | python -m json.tool
```

### 5. Seed sample data (optional)

```bash
python manage.py seed_posts
```

This creates sample authors, posts, comments, tags, and categories to explore the demo.

---

## OpenSearch Integration

Models can be automatically synced to OpenSearch for full-text search capabilities.

### Enable OpenSearch sync

In your model, add `opensearch_sync = True`:

```python
from dynamo_backend import DynamoModel, CharField

class Post(DynamoModel):
    class Meta:
        opensearch_sync = True  # Auto-sync to OpenSearch
        opensearch_index = "posts"  # Optional custom index name
    
    title = CharField(max_length=200)
    content = CharField()
```

### Configuration

Add to `settings.py`:

```python
OPENSEARCH_CONFIG = {
    'enabled': True,
    'host': 'localhost',
    'port': 9200,
    'use_ssl': False,
    'verify_certs': False,
}
```

### Reindex all documents

```bash
python manage.py opensearch_reindex
```

### Search API

```bash
# Search posts
curl "http://localhost:8000/api/posts/search/?q=django"
```

---

## Migrations

DDBDjango includes a custom migration system for DynamoDB schema evolution.

### Create migrations

```bash
python manage.py dmakemigrations
```

### Apply migrations

```bash
python manage.py dmigrate
```

Migrations support:
- Adding/removing fields
- Creating/deleting tables
- Adding/removing GSI indexes
- Field type changes

---

## AWS Cognito Authentication

The demo app includes AWS Cognito integration with a mock server for local development.

### Setup Cognito (local mock)

```bash
python manage.py setup_cognito
```

This creates a mock Cognito URL at http://localhost:8000/cognito/

### Configuration

```python
COGNITO_CONFIG = {
    'user_pool_id': 'local',
    'client_id': 'local-client',
    'region': 'us-east-1',
    'mock_mode': True,  # Use mock server for local dev
}
```

### Production setup

For production, set `mock_mode: False` and configure real Cognito credentials.

---

## Running tests

Tests use **moto** to mock DynamoDB in-process — no LocalStack or AWS account needed.

```bash
pytest
```

Run only integration tests (requires LocalStack):

```bash
docker-compose up -d
pytest -m integration
```

---

## dynamo_backend API reference

### Model definition

```python
from dynamo_backend import DynamoModel, CharField, IntegerField, BooleanField, DateTimeField

class Article(DynamoModel):
    class Meta:
        table_name = "articles"      # defaults to "<app_label>_<modelname>"

    title      = CharField(max_length=200, nullable=False)
    published  = BooleanField(default=False)
    view_count = IntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

### Available fields

| Field | DynamoDB type | Extra options |
|---|---|---|
| `CharField` | S | `max_length` |
| `IntegerField` | N | — |
| `FloatField` | N | — |
| `BooleanField` | BOOL | — |
| `DateTimeField` | S (ISO-8601) | `auto_now`, `auto_now_add` |
| `JSONField` | M / L | — |
| `UUIDField` | S | auto-generates UUID4 by default |
| `ListField` | L | — |

All fields accept `nullable=True/False`, `default=<value or callable>`, `index=True`.

### QuerySet cheat sheet

```python
# Create
post = Post.objects.create(title="Hello", slug="hello", author_pk=author.pk)

# Retrieve
post = Post.objects.get(pk="<uuid>")

# Filter
posts = Post.objects.filter(author_pk=author.pk, published=True)
posts = Post.objects.filter(title__contains="Django")
posts = Post.objects.filter(view_count__gte=100)
posts = Post.objects.filter(tags__isnull=False)

# Exclude
drafts = Post.objects.exclude(published=True)

# Ordering (in-memory)
posts = Post.objects.order_by("-created_at")

# Slice helpers
first = Post.objects.first()
count = Post.objects.count()
dicts = Post.objects.values("title", "slug")

# Update
post.title = "Updated"
post.save()

# Delete
post.delete()
Post.objects.filter(published=False).delete()

# Bulk create
Post.objects.bulk_create([Post(title=f"Post {i}", slug=f"post-{i}") for i in range(10)])

# get_or_create
post, created = Post.objects.get_or_create(slug="my-post", defaults={"title": "My Post"})
```

### Table management

```python
from dynamo_backend.table import ensure_table, delete_table

ensure_table(Post)   # create if not exists (idempotent)
delete_table(Post)   # drop — useful in tests
```

### Django settings

```python
DYNAMO_BACKEND = {
    "ENDPOINT_URL": "http://localhost:4566",  # omit for real AWS
    "REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "TABLE_PREFIX": "myapp_",                 # optional prefix for all tables
    "CREATE_TABLES_ON_STARTUP": True,
}
```

---

## Admin Panel

DDBDjango includes a custom Django admin integration with advanced search via OpenSearch.

### Register models

```python
from django.contrib import admin
from dynamo_backend.admin import DynamoModelAdmin
from .models import Post

@admin.register(Post)
class PostAdmin(DynamoModelAdmin):
    list_display = ['title', 'author_pk', 'published', 'created_at']
    list_filter = ['published']
    search_fields = ['title', 'content']  # Uses OpenSearch if enabled
```

### Access admin

1. Create superuser: Configure via Cognito or use mock auth
2. Navigate to http://localhost:8000/admin/
3. Use the DynamoDB-powered admin interface

---

## REST endpoints

### Authors
| Method | URL | Description |
|---|---|---|
| GET | `/api/authors/` | List all authors |
| POST | `/api/authors/` | Create author |
| GET | `/api/authors/<pk>/` | Get author |
| PUT | `/api/authors/<pk>/` | Update author |
| DELETE | `/api/authors/<pk>/` | Delete author |

### Posts
| Method | URL | Description |
|---|---|---|
| GET | `/api/posts/` | List posts (optional `?author_pk=`) |
| GET | `/api/posts/search/?q=<query>` | Search posts (requires OpenSearch) |
| POST | `/api/posts/` | Create post |
| GET | `/api/posts/<pk>/` | Get post + comments (increments view count) |
| PUT | `/api/posts/<pk>/` | Update post |
| DELETE | `/api/posts/<pk>/` | Delete post (cascades comments) |

### Comments
| Method | URL | Description |
|---|---|---|
| POST | `/api/posts/<pk>/comments/` | Add comment to post |
| DELETE | `/api/comments/<pk>/` | Delete comment |

### Tags & Categories
| Method | URL | Description |
|---|---|---|
| GET | `/api/tags/` | List all tags |
| GET | `/api/categories/` | List all categories |

### Frontend Pages
| URL | Description |
|---|---|
| `/` | Homepage with recent posts |
| `/explorer/` | Browse all posts, tags, categories |
| `/write/` | Create a new post |
| `/post/<slug>/` | View post details |
| `/author/<pk>/` | View author profile |
| `/tag/<pk>/` | View posts by tag |
| `/category/<pk>/` | View posts by category |

---

## Contributing & Development

### Project Structure

- **dynamo_backend/** - Core library
  - `models.py` - DynamoModel base class
  - `fields.py` - Field types
  - `queryset.py` - Query API
  - `manager.py` - Model manager
  - `opensearch_sync.py` - OpenSearch integration
  - `migration_*.py` - Migration system
  - `admin.py` - Admin integration
  - `backends/dynamodb/` - Database backend

- **demo_app/** - Example application
  - `models.py` - Blog models (Author, Post, Comment, etc.)
  - `views.py` - REST API views
  - `frontend_views.py` - Template views
  - `templates/` - HTML templates
  - `management/commands/` - Management commands

### Running the full stack

```bash
# Start all services
docker-compose up -d

# Run migrations
python manage.py dmigrate

# Seed data
python manage.py seed_posts

# Start server
python manage.py runserver
```

---

## License

MIT

---

## Credits

Built with Django, DynamoDB, and OpenSearch.
