# DDBDjango

A Django application with a **DynamoDB backend** and **OpenSearch integration** — no relational DB required.

## What's in the box

| Path                 | Purpose                                           |
| -------------------- | ------------------------------------------------- |
| `dynamo_backend/`    | The DynamoDB backend library with OpenSearch sync |
| `demo_app/`          | Full-featured blog demo with frontend templates   |
| `config/`            | Django project settings & routing                 |
| `tests/`             | Unit + view test suite (moto)                     |
| `docker-compose.yml` | LocalStack + OpenSearch for local development     |

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
┌──────────────────────────────────────────────────────┐
│                    Django App                         │
│  views.py  ──►  models.py (standard Django models)   │
│                     ↓                                 │
│              django.db.models.Model                   │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│            dynamo_backend (Django backend)            │
│                                                       │
│  router.py ──► backends/dynamodb/ ──► connection.py  │
│       │              │                     │          │
│   table.py    opensearch_sync.py   (boto3 resource)  │
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

- **Standard Django Models** — Uses regular `django.db.models.Model` with a custom database backend for DynamoDB.
- **Transparent Integration** — Write normal Django models; the backend handles DynamoDB persistence automatically.
- **UUID primary keys** — Uses UUIDField as primary keys (stored as strings in DynamoDB).
- **PAY_PER_REQUEST billing** — No capacity planning needed.
- **Indexed fields** — Mark fields with `db_index=True` to create Global Secondary Indexes for efficient filtering.
- **Standard Relationships** — ForeignKey, OneToOneField, and ManyToManyField work as expected.
- **Auto table creation** — Tables are created on Django startup (configurable).

---

## Quick start

**For detailed setup instructions, see [Local Development Setup](#local-development-setup) below.**

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start LocalStack

```bash
docker-compose up -d
```

### 3. Run the development server

```bash
python manage.py migrate
python manage.py runserver
```

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

# Create a post (using author's id from previous response)
curl -s -X POST http://localhost:8000/api/posts/ \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello DynamoDB","slug":"hello-dynamodb","author":"<author-id>","published":true}' | python -m json.tool

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

In your model's Meta class, add `opensearch_sync = True`:

```python
from django.db import models

class Post(models.Model):
    class Meta:
        opensearch_sync = True  # Auto-sync to OpenSearch
        opensearch_index = "posts"  # Optional custom index name

    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
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

DDBDjango uses **standard Django migrations** to manage schema changes.

### Create migrations

```bash
python manage.py makemigrations
```

### Apply migrations

```bash
python manage.py migrate
```

**How it works:**

- **`create_model`** - Creates DynamoDB table with GSIs for indexed fields
- **`delete_model`** - Deletes DynamoDB table
- **`add_field` / `remove_field`** - No-op (DynamoDB is schemaless)
- **`add_index` / `remove_index`** - Creates/deletes GSIs

DynamoDB is schemaless, so most field changes don't require migrations. You only need migrations when:

- Creating/deleting models (tables)
- Adding/removing indexes (`db_index=True`)
- Adding/removing ForeignKey fields (creates GSIs)

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

## Local Development Setup

### Python Version Requirements

This project requires **Python 3.10 or higher**. Here's how to set it up:

#### Check your Python version:
```bash
python3 --version
```

#### If you need to install/upgrade Python:

**macOS (using Homebrew):**
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12 (or latest)
brew install python@3.12

# Verify installation
python3.12 --version

# Create venv with specific Python version
python3.12 -m venv .venv
```

**macOS (using pyenv - recommended for multiple Python versions):**
```bash
# Install pyenv
brew install pyenv

# Install Python 3.12
pyenv install 3.12.0

# Set it as local version for this project
pyenv local 3.12.0

# Create venv
python -m venv .venv
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
python3.12 -m venv .venv
```

**Windows:**
Download and install from [python.org](https://www.python.org/downloads/)

### Quick commands (using Makefile)

```bash
make install      # Create venv and install dependencies
make docker-up    # Start LocalStack
make migrate      # Run migrations
make seed         # Seed sample data
make dev          # Start development server
make test         # Run tests
make help         # Show all available commands
```

### Manual setup

```bash
# 1. Clone the repository
git clone https://github.com/johnemcbride/DDBDjango.git
cd DDBDjango

# 2. Create and activate a virtual environment (use your Python version)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Verify you're in the venv (should show .venv path)
which python

# 3. Upgrade pip (important!)
pip install --upgrade pip

# 4. Install dependencies
pip install -r requirements.txt

# 5. Start LocalStack (for DynamoDB and OpenSearch)
docker-compose up -d

# 6. Run migrations
python manage.py migrate

# 7. Seed sample data (optional)
python manage.py seed_posts

# 8. Start the development server
python manage.py runserver
```

### Running tests

Tests use **moto** to mock DynamoDB in-process — no LocalStack or AWS account needed.

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_demo_app.py

# Run only integration tests (requires LocalStack)
docker-compose up -d
pytest -m integration
```

### Troubleshooting

**Issue: `pip install -r requirements.txt` fails**
```bash
# 1. Make sure you're using Python 3.10+ 
python --version

# 2. If Python version is too old, create new venv with newer Python
rm -rf .venv
python3.12 -m venv .venv  # or python3.11, python3.10, etc.
source .venv/bin/activate

# 3. Upgrade pip first
pip install --upgrade pip

# 4. Try installing again
pip install -r requirements.txt

# Alternative: Install packages individually if batch install fails
pip install django boto3 botocore opensearch-py pytest pytest-django "moto[dynamodb]"
```

**Issue: `ModuleNotFoundError` when running tests**
```bash
# Verify you're in the virtual environment (you should see (.venv) in prompt)
which python  # Should show path to .venv/bin/python

# If not activated:
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

**Issue: Python version mismatch**
```bash
# Check Python version in venv
.venv/bin/python --version

# If wrong version, recreate venv with correct Python
rm -rf .venv
python3.12 -m venv .venv  # Use your preferred version
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Issue: DynamoDB connection errors**
```bash
# Ensure LocalStack is running
docker-compose ps

# Restart if needed
docker-compose restart

# Check logs
docker-compose logs dynamodb
```

**Issue: `command not found: python` on macOS**
```bash
# Use python3 explicitly
python3 --version

# Or create an alias (add to ~/.zshrc or ~/.bashrc)
alias python=python3
```

---

## dynamo_backend API reference

### Model definition

Use **standard Django models** — DynamoDB persistence is completely transparent:

```python
from django.db import models
import uuid

class Article(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    published = models.BooleanField(default=False)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "myapp"
```

### Supported field types

All standard Django fields are supported:

| Django Field      | DynamoDB Type | Notes                        |
| ----------------- | ------------- | ---------------------------- |
| `CharField`       | S             | Stores as string             |
| `TextField`       | S             | Stores as string             |
| `IntegerField`    | N             | Stores as number             |
| `FloatField`      | N             | Stores as number             |
| `BooleanField`    | BOOL          | Native boolean               |
| `DateTimeField`   | S             | ISO-8601 format              |
| `DateField`       | S             | ISO-8601 format              |
| `EmailField`      | S             | Stores as string             |
| `URLField`        | S             | Stores as string             |
| `JSONField`       | M/L           | Native DynamoDB Map/List     |
| `UUIDField`       | S             | Recommended for primary keys |
| `ForeignKey`      | S             | Stores related object's pk   |
| `OneToOneField`   | S             | Stores related object's pk   |
| `ManyToManyField` | —             | Creates join table           |

Use `db_index=True` on fields for efficient filtering (creates GSI).

### QuerySet cheat sheet

Use **standard Django ORM** syntax:

```python
# Create
post = Post.objects.create(title="Hello", slug="hello", author=author)

# Retrieve
post = Post.objects.get(pk="<uuid>")

# Filter
posts = Post.objects.filter(author=author, published=True)
posts = Post.objects.filter(title__contains="Django")
posts = Post.objects.filter(view_count__gte=100)
posts = Post.objects.filter(labels__isnull=False)

# Exclude
drafts = Post.objects.exclude(published=True)

# Ordering (in-memory)
posts = Post.objects.order_by("-created_at")

# Relationships work normally
author = post.author  # ForeignKey traversal
comments = post.comments.all()  # Reverse ForeignKey
tags = post.labels.all()  # ManyToMany

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
Post.objects.bulk_create([Post(title=f"Post {i}", slug=f"post-{i}", author=author) for i in range(10)])

# get_or_create
post, created = Post.objects.get_or_create(slug="my-post", defaults={"title": "My Post", "author": author})
```

### Database configuration

Add the DynamoDB backend to your `DATABASES` setting:

```python
DATABASES = {
    "default": {
        "ENGINE": "dynamo_backend.backends.dynamodb",
        "NAME": "default",
        "ENDPOINT_URL": "http://localhost:4566",  # LocalStack
        "REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    }
}

DATABASE_ROUTERS = ["dynamo_backend.router.DynamoRouter"]
```

### Additional settings

```python
# Optional: Auto-create tables on startup
DYNAMO_BACKEND = {
    "CREATE_TABLES_ON_STARTUP": True,
    "TABLE_PREFIX": "myapp_",  # optional prefix for all tables
}
```

---

## Admin Panel

DDBDjango includes a custom Django admin integration with advanced search via OpenSearch.

### Register models

```python
from django.contrib import admin
from .models import Post

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'published', 'created_at']
    list_filter = ['published']
    search_fields = ['title', 'content']  # Uses OpenSearch if enabled
    raw_id_fields = ['author']  # For ForeignKey fields
```

### Access admin

1. Create superuser: Configure via Cognito or use mock auth
2. Navigate to http://localhost:8000/admin/
3. Use the DynamoDB-powered admin interface

---

## REST endpoints

### Authors

| Method | URL                  | Description      |
| ------ | -------------------- | ---------------- |
| GET    | `/api/authors/`      | List all authors |
| POST   | `/api/authors/`      | Create author    |
| GET    | `/api/authors/<pk>/` | Get author       |
| PUT    | `/api/authors/<pk>/` | Update author    |
| DELETE | `/api/authors/<pk>/` | Delete author    |

### Posts

| Method | URL                            | Description                                 |
| ------ | ------------------------------ | ------------------------------------------- |
| GET    | `/api/posts/`                  | List posts (optional `?author=<id>`)        |
| GET    | `/api/posts/search/?q=<query>` | Search posts (requires OpenSearch)          |
| POST   | `/api/posts/`                  | Create post                                 |
| GET    | `/api/posts/<pk>/`             | Get post + comments (increments view count) |
| PUT    | `/api/posts/<pk>/`             | Update post                                 |
| DELETE | `/api/posts/<pk>/`             | Delete post (cascades comments)             |

### Comments

| Method | URL                         | Description         |
| ------ | --------------------------- | ------------------- |
| POST   | `/api/posts/<pk>/comments/` | Add comment to post |
| DELETE | `/api/comments/<pk>/`       | Delete comment      |

### Tags & Categories

| Method | URL                | Description         |
| ------ | ------------------ | ------------------- |
| GET    | `/api/tags/`       | List all tags       |
| GET    | `/api/categories/` | List all categories |

### Frontend Pages

| URL               | Description                        |
| ----------------- | ---------------------------------- |
| `/`               | Homepage with recent posts         |
| `/explorer/`      | Browse all posts, tags, categories |
| `/write/`         | Create a new post                  |
| `/post/<slug>/`   | View post details                  |
| `/author/<pk>/`   | View author profile                |
| `/tag/<pk>/`      | View posts by tag                  |
| `/category/<pk>/` | View posts by category             |

---

## Contributing & Development

### Project Structure

- **dynamo_backend/** - Core library

  - `backends/dynamodb/` - Django database backend for DynamoDB
  - `router.py` - Database router to direct models to DynamoDB
  - `opensearch_sync.py` - OpenSearch integration
  - `migration_*.py` - Migration system
  - `admin.py` - Admin integration
  - `connection.py` - DynamoDB connection management
  - `table.py` - Table creation/management

- **demo_app/** - Example application
  - `models.py` - Standard Django models (Author, Post, Comment, etc.)
  - `views.py` - REST API views
  - `frontend_views.py` - Template views
  - `templates/` - HTML templates
  - `management/commands/` - Management commands

### Running the full stack

```bash
# Start all services
docker-compose up -d

# Run migrations
python manage.py migrate

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
