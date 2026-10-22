from django.contrib import admin

from payments.forms import DebtServicePaymentForm, MaintenanceCategoryForm, TenantPaymentForm, VendorBillForm, VendorForm, VendorPaymentForm
from payments.models import (
    DebtServicePayment,
    MaintenanceCategory,
    PaymentWorkflowSettings,
    SecurityDepositEvent,
    TenantPayment,
    TenantPaymentApplication,
    Vendor,
    VendorBill,
    VendorBillApprovalEvent,
    VendorPayment,
    WorkflowAuthorization,
)
from payments.approval_services import VendorBillApprovalService
from payments.services import VendorPaymentService, VendorService


@admin.register(PaymentWorkflowSettings)
class PaymentWorkflowSettingsAdmin(admin.ModelAdmin):
    fields = ["charge_type_priority"]

    def has_add_permission(self, request):  # pragma: no cover - admin behavior
        return not PaymentWorkflowSettings.objects.exists()


class TenantPaymentApplicationInline(admin.TabularInline):
    model = TenantPaymentApplication
    extra = 0
    fields = ["charge", "amount_applied", "sync_record"]
    readonly_fields = ["charge", "amount_applied", "sync_record"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TenantPayment)
class TenantPaymentAdmin(admin.ModelAdmin):
    form = TenantPaymentForm
    list_display = ["tenant", "property", "payment_date", "amount", "status", "allocated_amount", "unapplied_amount"]
    list_filter = ["status", "payment_method", "property"]
    search_fields = ["tenant__name", "property__name", "reference"]
    inlines = [TenantPaymentApplicationInline]


@admin.register(TenantPaymentApplication)
class TenantPaymentApplicationAdmin(admin.ModelAdmin):
    list_display = ["payment", "charge", "amount_applied", "sync_record", "created_at"]
    search_fields = ["payment__tenant__name", "charge__description"]
    readonly_fields = ["payment", "charge", "amount_applied", "sync_record"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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

    def save_model(self, request, obj, form, change):  # pragma: no cover - admin behavior
        VendorService.save_and_sync_vendor(obj)


@admin.register(MaintenanceCategory)
class MaintenanceCategoryAdmin(admin.ModelAdmin):
    form = MaintenanceCategoryForm
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]


@admin.register(VendorBill)
class VendorBillAdmin(admin.ModelAdmin):
    form = VendorBillForm
    list_display = ["vendor", "property", "unit", "bill_date", "amount", "approval_status", "status"]
    list_filter = ["approval_status", "status", "expense_category", "property"]
    search_fields = ["vendor__name", "property__name", "unit__name", "repair_notes", "notes"]
    readonly_fields = [
        "status", "sync_record", "approval_status", "created_by", "submitted_by", "submitted_at",
        "submission_version", "approved_fingerprint", "decision_by", "decision_at", "decision_reason",
    ]

    def save_model(self, request, obj, form, change):  # pragma: no cover - admin behavior
        VendorBillApprovalService.save_draft(obj, actor=request.user)


@admin.register(VendorPayment)
class VendorPaymentAdmin(admin.ModelAdmin):
    form = VendorPaymentForm
    list_display = ["vendor", "vendor_bill", "payment_date", "amount", "payment_method", "status"]
    list_filter = ["status", "payment_method", "is_credit_card_payoff"]
    search_fields = ["vendor__name", "vendor_bill__vendor__name", "memo", "notes"]
    readonly_fields = ["status", "sync_record", "submission_id", "submission_hash", "initiated_by"]

    def save_model(self, request, obj, form, change):  # pragma: no cover - admin behavior
        VendorPaymentService.save_and_sync_payment(obj, actor=request.user)


@admin.register(WorkflowAuthorization)
class WorkflowAuthorizationAdmin(admin.ModelAdmin):
    list_display = ["user", "can_approve_vendor_bills", "can_pay_vendor_bills", "updated_by", "updated_at"]
    readonly_fields = ["user", "can_approve_vendor_bills", "can_pay_vendor_bills", "updated_by", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VendorBillApprovalEvent)
class VendorBillApprovalEventAdmin(admin.ModelAdmin):
    list_display = ["bill", "action", "actor", "submission_version", "created_at"]
    readonly_fields = ["bill", "action", "actor", "submission_version", "financial_fingerprint", "reason", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DebtServicePayment)
class DebtServicePaymentAdmin(admin.ModelAdmin):
    form = DebtServicePaymentForm
    list_display = ["property", "lender", "payment_date", "total_amount", "principal_amount", "interest_amount", "status"]
    list_filter = ["status", "property"]
    search_fields = ["lender__name", "property__name", "memo"]
