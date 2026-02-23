"""
lambda_handler.py
~~~~~~~~~~~~~~~~~
AWS Lambda entry-point for the DDBDjango demo app.

Wraps Django's WSGI application with apig_wsgi so it can be invoked by
an API Gateway HTTP API (payload format 2.0) or REST API (payload format 1.0).

Expected Lambda environment variables (set by deploy_lambda.sh):
  DJANGO_SETTINGS_MODULE       = config.settings
  DYNAMO_ENDPOINT_URL          = http://localhost.localstack.cloud:4566
  DYNAMO_SKIP_STARTUP          = 1  (tables already exist; skip auto-create)
  AWS_DEFAULT_REGION           = us-east-1
  AWS_ACCESS_KEY_ID            = test
  AWS_SECRET_ACCESS_KEY        = test
"""

import os

# Must be set before Django imports.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Tables are already created by `manage.py migrate`; skip the startup scan.
os.environ.setdefault("DYNAMO_SKIP_STARTUP", "1")

from apig_wsgi import make_lambda_handler  # noqa: E402
from config.wsgi import application  # noqa: E402  (triggers django.setup())

handler = make_lambda_handler(application)
