"""
Django settings for DDBDjango.

- Uses the custom dynamo_backend instead of any relational DB.
- Reads AWS / LocalStack config from environment variables.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────── security

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-do-not-use-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# ─────────────────────────────────────────────────────── apps

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dynamo_backend.apps.DynamoBackendConfig",
    "demo_app.apps.DemoAppConfig",
]

# ─────────────────────────────────────────────────────── middleware

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# ─────────────────────────────────────────────────────── urls / wsgi

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# ─────────────────────────────────────────────────────── templates

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# ── Auth ─────────────────────────────────────────────────────────────
# Custom user model stored in DynamoDB — no SQLite, no M2M groups/perms.
# Superusers have full access; is_staff lets users into the admin.
AUTH_USER_MODEL = "dynamo_backend.DynamoUser"
AUTHENTICATION_BACKENDS = ["dynamo_backend.auth_backend.DynamoAuthBackend"]

# ─────────────────────────────────────────────────────── database
# DynamoDB is the one and only database — Django's default.
# All built-in tooling (migrations, admin, check_migrations, …) targets it
# directly without any router.

DATABASES = {
    "default": {
        "ENGINE": "dynamo_backend.backends.dynamodb",
        # LocalStack endpoint for local dev; empty / None for real AWS
        "ENDPOINT_URL": os.environ.get("DYNAMO_ENDPOINT_URL", "http://localhost:4566"),
        "REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        "TEST": {"NAME": "test_dynamodb"},
        # ── Behaviour options ────────────────────────────────────────────────
        "OPTIONS": {
            # Prefix all DynamoDB table names (useful for shared AWS accounts)
            "table_prefix": os.environ.get("DYNAMO_TABLE_PREFIX", ""),
            # Allow full-table scans when a non-pk filter is used.
            # Set to False to catch accidental slow queries in production.
            "scan_on_filter": True,
            # Use strongly consistent reads (False = eventual consistency, cheaper)
            "consistent_read": False,
            # Auto-create a GSI for every db_index=True field and every ForeignKey.
            "auto_gsi": True,
            # BatchGetItem chunk size (DynamoDB max is 100; keep under 25 for safety)
            "batch_chunk_size": 25,
            # DynamoDB billing mode: PAY_PER_REQUEST | PROVISIONED
            "billing_mode": "PAY_PER_REQUEST",
        },
    },
}

# ── Legacy DYNAMO_BACKEND dict (kept for backward compat with old table utils)
# New code should use DATABASES['default'] directly.
DYNAMO_BACKEND = {
    "ENDPOINT_URL": os.environ.get("DYNAMO_ENDPOINT_URL", "http://localhost:4566"),
    "REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    "TABLE_PREFIX": os.environ.get("DYNAMO_TABLE_PREFIX", ""),
    "CREATE_TABLES_ON_STARTUP": False,  # handled by apps.py / migrations now
}

# ─────────────────────────────────────────────────────── i18n

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─────────────────────────────────────────────────────── static

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
