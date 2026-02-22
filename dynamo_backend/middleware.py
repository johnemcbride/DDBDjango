"""
dynamo_backend.middleware
~~~~~~~~~~~~~~~~~~~~~~~~~
Django middleware for the DynamoDB backend.

DynamoCacheMiddleware
---------------------
Resets the per-request FK lookup cache at the start of every request.
This ensures that cached items from one request cannot leak into another,
and that the cache stays small (it only holds items fetched during the
current request).

The cache is also reset by DynamoPanel.process_request when django-debug-
toolbar is active, but DynamoCacheMiddleware makes the cache work correctly
even when DjDT is not installed or the toolbar is disabled for the current
request (e.g. AJAX requests, API endpoints).

Usage — add before session/auth middleware in settings.py::

    MIDDLEWARE = [
        "dynamo_backend.middleware.DynamoCacheMiddleware",
        ...
    ]
"""

from __future__ import annotations


class DynamoCacheMiddleware:
    """Reset the DynamoDB per-request FK cache at the start of each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from dynamo_backend.debug_panel import reset_request_cache
            reset_request_cache()
        except Exception:
            pass
        return self.get_response(request)
