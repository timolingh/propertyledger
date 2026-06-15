from django.contrib import admin

from ledgeros.models import (
    Lease,
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    Unit,
)


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


class PropertyLedgerAccountMappingInline(admin.TabularInline):
    model = PropertyLedgerAccountMapping
    extra = 0
    fields = [
        "mapping_key",
        "ledgeros_account_id",
        "ledgeros_account_name",
        "ledgeros_account_type",
        "is_required",
        "is_enabled",
        "notes",
    ]
    show_change_link = True


@admin.register(PropertyLedgerSetup)
class PropertyLedgerSetupAdmin(admin.ModelAdmin):
    fields = [
        "setup_status",
        "ledgeros_entity_id",
        "ledgeros_entity_name",
        "ledgeros_accounting_period_id",
        "ledgeros_accounting_period_name",
        "last_ledgeros_health_check_at",
        "last_ledgeros_health_check_healthy",
        "last_ledgeros_health_check_payload",
        "last_setup_smoke_at",
        "last_setup_smoke_healthy",
        "last_setup_smoke_payload",
        "validated_at",
        "completed_at",
    ]
    inlines = [PropertyLedgerAccountMappingInline]

    def has_add_permission(self, request):  # pragma: no cover - admin behavior
        return not PropertyLedgerSetup.objects.exists()


@admin.register(PropertyLedgerAccountMapping)
class PropertyLedgerAccountMappingAdmin(admin.ModelAdmin):
    list_display = [
        "mapping_key",
        "setup",
        "ledgeros_account_name",
        "ledgeros_account_id",
        "ledgeros_account_type",
        "is_required",
        "is_enabled",
    ]
    list_filter = ["mapping_key", "is_required", "is_enabled"]
    search_fields = [
        "mapping_key",
        "ledgeros_account_id",
        "ledgeros_account_name",
        "ledgeros_account_type",
    ]


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "phone", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "email", "phone"]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "primary_owner", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "primary_owner__name"]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["name", "property", "status", "created_at"]
    list_filter = ["status", "property"]
    search_fields = ["name", "property__name"]


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "phone", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "email", "phone"]


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = [
        "unit",
        "tenant",
        "status",
        "lease_start_date",
        "rent_effective_date",
        "base_monthly_rent_amount",
        "base_monthly_rent_currency",
        "deposit_required_amount",
        "deposit_required_currency",
    ]
    list_filter = ["status", "base_monthly_rent_currency", "deposit_required_currency"]
    search_fields = ["unit__name", "unit__property__name", "tenant__name"]


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
