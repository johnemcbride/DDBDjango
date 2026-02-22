"""
dynamo_backend.apps
~~~~~~~~~~~~~~~~~~~
AppConfig that auto-creates DynamoDB tables on Django startup
(when DYNAMO_BACKEND['CREATE_TABLES_ON_STARTUP'] is True).
"""

from django.apps import AppConfig


class DynamoBackendConfig(AppConfig):
    name = "dynamo_backend"
    verbose_name = "DynamoDB Backend"

    def ready(self) -> None:
        import os
        if os.environ.get("DYNAMO_SKIP_STARTUP"):
            return
        from .connection import get_config
        if not get_config().get("create_tables_on_startup", True):
            return
        self._ensure_all_tables()

    @staticmethod
    def _ensure_all_tables() -> None:
        # Force-import all installed apps' models modules so the metaclass
        # registers every DynamoModel subclass before we iterate.
        from django.apps import apps as django_apps
        import importlib
        for app_config in django_apps.get_app_configs():
            try:
                importlib.import_module(f"{app_config.name}.models")
            except ModuleNotFoundError:
                pass

        from .models import _dynamo_model_registry
        from .table import ensure_table

        for model in _dynamo_model_registry:
            try:
                ensure_table(model)
            except Exception as exc:
                import warnings
                warnings.warn(
                    f"dynamo_backend: could not ensure table for {model.__name__}: {exc}",
                    stacklevel=2,
                )
