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
            # include_auto_created=True so auto-generated M2M through tables
            # (e.g. Post_labels for ManyToManyField without a custom through
            # model) are also ensured on startup.
            for model in app_config.get_models(include_auto_created=True):
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
