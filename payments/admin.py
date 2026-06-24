from django.contrib import admin

from payments.models import PaymentWorkflowSettings, SecurityDepositEvent, TenantPayment, TenantPaymentApplication


@admin.register(PaymentWorkflowSettings)
class PaymentWorkflowSettingsAdmin(admin.ModelAdmin):
    fields = ["charge_type_priority"]

    def has_add_permission(self, request):  # pragma: no cover - admin behavior
        return not PaymentWorkflowSettings.objects.exists()


class TenantPaymentApplicationInline(admin.TabularInline):
    model = TenantPaymentApplication
    extra = 0
    fields = ["charge", "amount_applied", "sync_record"]
    readonly_fields = ["sync_record"]


@admin.register(TenantPayment)
class TenantPaymentAdmin(admin.ModelAdmin):
    list_display = ["tenant", "property", "payment_date", "amount", "status", "allocated_amount"]
    list_filter = ["status", "payment_method", "property"]
    search_fields = ["tenant__name", "property__name", "reference"]
    inlines = [TenantPaymentApplicationInline]


@admin.register(TenantPaymentApplication)
class TenantPaymentApplicationAdmin(admin.ModelAdmin):
    list_display = ["payment", "charge", "amount_applied", "sync_record", "created_at"]
    search_fields = ["payment__tenant__name", "charge__description"]


@admin.register(SecurityDepositEvent)
class SecurityDepositEventAdmin(admin.ModelAdmin):
    list_display = ["tenant", "property", "unit", "event_type", "event_date", "amount", "status"]
    list_filter = ["status", "event_type", "property"]
    search_fields = ["tenant__name", "property__name", "unit__name", "lease__id", "description"]

