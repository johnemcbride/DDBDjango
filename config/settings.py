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
    "django.contrib.sites",
    "dynamo_backend.apps.DynamoBackendConfig",
    "demo_app.apps.DemoAppConfig",
    # ── django-allauth ───────────────────────────────────────────────
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.amazon_cognito",
]

SITE_ID = 1

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]

# ─────────────────────────────────────────────────────── middleware

MIDDLEWARE = [
    "dynamo_backend.middleware.DynamoCacheMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # allauth account middleware (required for allauth 56+)
    "allauth.account.middleware.AccountMiddleware",
]

if DEBUG:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

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
# Stock auth.User is used — no custom user model.
# apps.py patches auth.User.groups / user_permissions with
# DynamoManyToManyDescriptor so M2M goes through DynamoDB two-step reads.

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

# ── DYNAMO_BACKEND — used by dynamo_backend.connection (legacy connection helper)
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

# ─────────────────────────────────────────────────────── sessions
# Use cache-backed sessions so Django never tries to INSERT/UPDATE the
# django_session DynamoDB table.  The default LocMemCache is already
# configured and works fine for local development.  For multi-process
# production deployments swap CACHES to Redis/Memcached.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ─────────────────────────────────────────────── debug toolbar

# Only injected on requests from localhost (the default show_toolbar check)
INTERNAL_IPS = ["127.0.0.1"]
# ─────────────────────────────────────────────────────── opensearch (via LocalStack)
# OpenSearch is managed by LocalStack — no separate container needed.
# The boto3 opensearch client will create/re-use a domain inside LocalStack.
# Set OPENSEARCH_ENDPOINT_URL='' to disable and fall back to DDB scans.
OPENSEARCH_ENDPOINT_URL = os.environ.get(
    "OPENSEARCH_ENDPOINT_URL",
    # default: same LocalStack gateway as DynamoDB
    os.environ.get("DYNAMO_ENDPOINT_URL", "http://localhost:4566"),
)
OPENSEARCH_DOMAIN_NAME = os.environ.get("OPENSEARCH_DOMAIN_NAME", "ddbdjango")
DEBUG_TOOLBAR_PANELS = [
    # — Our custom panel first so it's the default selected tab —
    "dynamo_backend.debug_panel.DynamoPanel",
    # — Standard DjDT panels —
    "debug_toolbar.panels.history.HistoryPanel",
    "debug_toolbar.panels.versions.VersionsPanel",
    "debug_toolbar.panels.timer.TimerPanel",
    "debug_toolbar.panels.settings.SettingsPanel",
    "debug_toolbar.panels.headers.HeadersPanel",
    "debug_toolbar.panels.request.RequestPanel",
    "debug_toolbar.panels.templates.TemplatesPanel",
    "debug_toolbar.panels.alerts.AlertsPanel",
    "debug_toolbar.panels.staticfiles.StaticFilesPanel",
    "debug_toolbar.panels.redirects.RedirectsPanel",
    "debug_toolbar.panels.profiling.ProfilingPanel",
]

# ─────────────────────────────────────────────── authentication
AUTHENTICATION_BACKENDS = [
    # Standard Django auth (username/password, admin)
    "django.contrib.auth.backends.ModelBackend",
    # allauth social auth backend
    "allauth.account.auth_backends.AuthenticationBackend",
]

# ───────────────────────── allauth core
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
# ACCOUNT_SIGNUP_FIELDS uses * suffix to mark required fields (allauth 65+)
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_EMAIL_VERIFICATION = "none"      # no outgoing email in local dev
ACCOUNT_SIGNUP_REDIRECT_URL = "/"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = False
SOCIALACCOUNT_STORE_TOKENS = True
# Auto-connect social login to an existing account with the same email
# (prevents the "account already exists" signup prompt)
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# ─────────────────────────────────── allauth Cognito → LocalStack
# In local dev the Cognito mock runs inside Django itself at /cognito-mock/.
# Set COGNITO_DOMAIN to your real Cognito User Pool domain in production
# (or use LocalStack Pro for a proper local Cognito).
SOCIALACCOUNT_PROVIDERS = {
    "amazon_cognito": {
        "DOMAIN": os.environ.get(
            "COGNITO_DOMAIN",
            "http://localhost:8000/cognito-mock",  # local mock (dev default)
        ),
    }
}

# ─────────────────────────────────────────── messages → Bootstrap classes
from django.contrib.messages import constants as messages_constants
MESSAGE_TAGS = {
    messages_constants.DEBUG:   "secondary",
    messages_constants.INFO:    "info",
    messages_constants.SUCCESS: "success",
    messages_constants.WARNING: "warning",
    messages_constants.ERROR:   "danger",
}
