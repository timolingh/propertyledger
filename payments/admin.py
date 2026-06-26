from django.contrib import admin

from payments.forms import DebtServicePaymentForm, MaintenanceCategoryForm, VendorBillForm, VendorForm, VendorPaymentForm
from payments.models import (
    DebtServicePayment,
    MaintenanceCategory,
    PaymentWorkflowSettings,
    SecurityDepositEvent,
    TenantPayment,
    TenantPaymentApplication,
    Vendor,
    VendorBill,
    VendorPayment,
)


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
    list_display = ["tenant", "property", "payment_date", "amount", "status", "allocated_amount", "unapplied_amount"]
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


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    form = VendorForm
    list_display = ["name", "email", "phone", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "email", "phone"]


@admin.register(MaintenanceCategory)
class MaintenanceCategoryAdmin(admin.ModelAdmin):
    form = MaintenanceCategoryForm
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]


@admin.register(VendorBill)
class VendorBillAdmin(admin.ModelAdmin):
    form = VendorBillForm
    list_display = ["vendor", "property", "unit", "bill_date", "amount", "expense_category", "status"]
    list_filter = ["status", "expense_category", "property"]
    search_fields = ["vendor__name", "property__name", "unit__name", "repair_notes", "notes"]


@admin.register(VendorPayment)
class VendorPaymentAdmin(admin.ModelAdmin):
    form = VendorPaymentForm
    list_display = ["vendor", "vendor_bill", "payment_date", "amount", "payment_method", "status"]
    list_filter = ["status", "payment_method", "is_credit_card_payoff"]
    search_fields = ["vendor__name", "vendor_bill__vendor__name", "memo", "notes"]


@admin.register(DebtServicePayment)
class DebtServicePaymentAdmin(admin.ModelAdmin):
    form = DebtServicePaymentForm
    list_display = ["property", "lender", "payment_date", "total_amount", "principal_amount", "interest_amount", "status"]
    list_filter = ["status", "property"]
    search_fields = ["lender__name", "property__name", "memo"]
