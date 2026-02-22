"""
dynamo_backend.apps
~~~~~~~~~~~~~~~~~~~
AppConfig that auto-creates DynamoDB tables on Django startup.

All installed apps' models are routed to the 'dynamodb' connection by
DynamoRouter, so we create a DynamoDB table for each concrete model
(including auth, sessions, contenttypes, and admin models).
"""

from django.apps import AppConfig


class DynamoBackendConfig(AppConfig):
    name = "dynamo_backend"
    verbose_name = "DynamoDB Backend"

    def import_models(self):
        """Also import DynamoUser so Django's model registry picks it up."""
        super().import_models()
        # user_model.py defines DynamoUser (AbstractBaseUser).  It must be
        # imported *after* the app registry is ready (Phase 2), so we do it
        # here rather than at module level in models.py or __init__.py.
        from . import user_model  # noqa: F401 – side-effect import

    def ready(self) -> None:
        import os
        if os.environ.get("DYNAMO_SKIP_STARTUP"):
            return
        self._ensure_all_tables()

    @staticmethod
    def _ensure_all_tables() -> None:
        """
        Create a DynamoDB table for every concrete model across all installed
        apps, using the 'dynamodb' connection's DatabaseCreation helper.
        """
        from django.apps import apps as django_apps
        from django.db import connections
        import importlib

        # Make sure all models modules are imported (so Meta is registered)
        for app_config in django_apps.get_app_configs():
            try:
                importlib.import_module(f"{app_config.name}.models")
            except ModuleNotFoundError:
                pass

        creation = connections["default"].creation

        for app_config in django_apps.get_app_configs():
            for model in app_config.get_models():
                # Skip abstract / proxy / unmanaged models
                if model._meta.abstract or model._meta.proxy or not model._meta.managed:
                    continue
                try:
                    creation.ensure_table(model)
                except Exception as exc:
                    import warnings
                    warnings.warn(
                        f"dynamo_backend: could not ensure table for "
                        f"{app_config.label}.{model.__name__}: {exc}",
                        stacklevel=2,
                    )
