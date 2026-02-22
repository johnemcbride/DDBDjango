# DDBDjango

A Django application with a **DynamoDB backend** — no relational DB required.

## What's in the box

| Path | Purpose |
|---|---|
| `dynamo_backend/` | The DynamoDB backend library (all-in-one) |
| `demo_app/` | Blog demo (Author → Post → Comment) |
| `config/` | Django project settings & routing |
| `tests/` | Unit + view test suite (moto) |
| `docker-compose.yml` | LocalStack for local development |

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
│       │                                    │          │
│   fields.py                          connection.py   │
│   table.py                          (boto3 resource) │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   AWS DynamoDB          │
          │   (or LocalStack 4566)  │
          └─────────────────────────┘
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

### 4. Try the API

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
| POST | `/api/posts/` | Create post |
| GET | `/api/posts/<pk>/` | Get post + comments (increments view count) |
| PUT | `/api/posts/<pk>/` | Update post |
| DELETE | `/api/posts/<pk>/` | Delete post (cascades comments) |

### Comments
| Method | URL | Description |
|---|---|---|
| POST | `/api/posts/<pk>/comments/` | Add comment to post |
| DELETE | `/api/comments/<pk>/` | Delete comment |
