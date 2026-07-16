from django.apps import AppConfig


class LedgerosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ledgeros"

    def ready(self) -> None:
        from . import signals  # noqa: F401
