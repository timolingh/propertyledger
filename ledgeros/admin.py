from django.contrib import admin

from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord


@admin.register(LedgerOSConnectionSettings)
class LedgerOSConnectionSettingsAdmin(admin.ModelAdmin):
    fields = [
        "base_url",
        "client_id",
        "hmac_secret_env_var",
        "api_key_env_var",
        "health_path",
        "timeout_seconds",
    ]

    def has_add_permission(self, request):  # pragma: no cover - admin behavior
        return not LedgerOSConnectionSettings.objects.exists()


@admin.register(LedgerOSSyncRecord)
class LedgerOSSyncRecordAdmin(admin.ModelAdmin):
    list_display = [
        "local_object_type",
        "local_object_id",
        "source_event_type",
        "external_id",
        "status",
        "attempt_count",
        "created_at",
    ]
    list_filter = ["status", "source_event_type", "created_at"]
    search_fields = [
        "local_object_type",
        "local_object_id",
        "source_event_type",
        "external_id",
        "idempotency_key",
    ]
