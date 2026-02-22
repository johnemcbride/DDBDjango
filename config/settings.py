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

# ─────────────────────────────────────────────────────── database
# We don't use Django's ORM / relational DB at all.
# A dummy sqlite config is kept here only to satisfy Django's
# system check (e.g. for django.contrib.auth checks).
# SQLite is used only for Django admin infrastructure (auth, sessions, admin log).
# All application data lives in DynamoDB.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ─────────────────────────────────────────────────────── DynamoDB / LocalStack

DYNAMO_BACKEND = {
    # Point at LocalStack for local dev; override via env var in production.
    "ENDPOINT_URL": os.environ.get("DYNAMO_ENDPOINT_URL", "http://localhost:4566"),
    "REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    "TABLE_PREFIX": os.environ.get("DYNAMO_TABLE_PREFIX", ""),
    "CREATE_TABLES_ON_STARTUP": True,
}

# ─────────────────────────────────────────────────────── i18n

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─────────────────────────────────────────────────────── static

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
