from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from ledgeros.models import Lease, Property, Tenant, TenantCharge, Unit
from payments.models import (
    DebtServicePayment,
    MaintenanceCategory,
    SecurityDepositEvent,
    TenantPayment,
    Vendor,
    VendorBill,
    VendorPayment,
    _operating_bank_account_name,
)


class _SyncEditableModelForm(forms.ModelForm):
    editable_after_sync_fields: tuple[str, ...] = ()

    def _apply_sync_edit_restrictions(self) -> None:
        if not self.instance or not self.instance.pk:
            return
        if not getattr(self.instance, "is_editable_after_sync", True):
            for name in self.fields:
                if name not in self.editable_after_sync_fields:
                    self.fields[name].disabled = True


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "email", "phone", "is_active", "notes"]


class MaintenanceCategoryForm(forms.ModelForm):
    class Meta:
        model = MaintenanceCategory
        fields = ["name", "description", "is_active"]


class TenantPaymentForm(forms.ModelForm):
    class Meta:
        model = TenantPayment
        fields = [
            "property",
            "tenant",
            "payment_date",
            "amount",
            "payment_method",
            "reference",
            "notes",
            "status",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        if self.instance and self.instance.pk and not self.instance.is_editable_after_sync:
            for name in self.fields:
                if name != "notes":
                    self.fields[name].disabled = True


class InvoicePaymentForm(forms.ModelForm):
    class Meta:
        model = TenantPayment
        fields = [
            "payment_date",
            "amount",
            "payment_method",
            "reference",
            "notes",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].help_text = (
            "Enter the amount received. Any excess can remain as tenant credit."
        )


class SecurityDepositEventForm(forms.ModelForm):
    class Meta:
        model = SecurityDepositEvent
        fields = [
            "property",
            "unit",
            "tenant",
            "lease",
            "event_type",
            "event_date",
            "amount",
            "description",
            "notes",
            "status",
        ]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["unit"].queryset = Unit.objects.select_related("property").all()
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        self.fields["lease"].queryset = Lease.objects.select_related("unit__property", "tenant").all()
        if self.instance and self.instance.pk and not self.instance.is_editable_after_sync:
            for name in self.fields:
                if name != "notes":
                    self.fields[name].disabled = True


class VendorBillForm(_SyncEditableModelForm):
    editable_after_sync_fields = ("notes",)

    class Meta:
        model = VendorBill
        fields = [
            "vendor",
            "property",
            "unit",
            "bill_date",
            "due_date",
            "amount",
            "expense_category",
            "maintenance_category",
            "repair_notes",
            "tenant_chargeable",
            "notes",
        ]
        widgets = {
            "bill_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendor"].queryset = Vendor.objects.filter(is_active=True)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["unit"].queryset = Unit.objects.select_related("property").all()
        self.fields["maintenance_category"].queryset = MaintenanceCategory.objects.filter(is_active=True)
        self._apply_sync_edit_restrictions()


class VendorPaymentForm(_SyncEditableModelForm):
    editable_after_sync_fields = ("memo", "notes")

    class Meta:
        model = VendorPayment
        fields = [
            "vendor",
            "vendor_bill",
            "payment_date",
            "amount",
            "payment_method",
            "bank_account_name",
            "credit_card_account_name",
            "memo",
            "check_number",
            "check_status",
            "is_credit_card_payoff",
            "notes",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendor"].queryset = Vendor.objects.filter(is_active=True)
        self.fields["vendor_bill"].queryset = VendorBill.objects.select_related("vendor", "property").all()
        self.fields["bank_account_name"].help_text = "Locked to the configured operating bank account for MVP vendor payments."
        if not self.instance or not self.instance.pk:
            try:
                self.fields["bank_account_name"].initial = _operating_bank_account_name()
            except ValidationError:
                self.fields["bank_account_name"].initial = ""
        self._apply_sync_edit_restrictions()


class DebtServicePaymentForm(_SyncEditableModelForm):
    editable_after_sync_fields = ("memo",)

    class Meta:
        model = DebtServicePayment
        fields = [
            "property",
            "lender",
            "payment_date",
            "total_amount",
            "principal_amount",
            "interest_amount",
            "payment_account_name",
            "loan_liability_account_name",
            "interest_expense_account_name",
            "memo",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["lender"].queryset = Vendor.objects.filter(is_active=True)
        self.fields["payment_account_name"].help_text = "Locked to the configured operating bank account for MVP debt-service payments."
        if not self.instance or not self.instance.pk:
            try:
                self.fields["payment_account_name"].initial = _operating_bank_account_name()
            except ValidationError:
                self.fields["payment_account_name"].initial = ""
        self._apply_sync_edit_restrictions()
