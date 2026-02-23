"""
Root conftest.py - pytest early configuration hook.  
Sets environment variables BEFORE pytest-django loads Django.
"""


def pytest_load_initial_conftests(early_config, parser, args):
    """
    This hook runs BEFORE pytest-django calls django.setup().
    Set environment variables here to configure Django for tests.
    """
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["DYNAMO_SKIP_STARTUP"] = "1"
    os.environ["DYNAMO_ENDPOINT_URL"] = ""  # empty → None → let moto intercept
