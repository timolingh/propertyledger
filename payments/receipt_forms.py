from decimal import Decimal

from django import forms

from payments.forms import TenantPaymentForm
from payments.receipt_services import receipt_waterfall


class WaterfallReceiptForm(TenantPaymentForm):
    invoice_amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="1. Open invoices")
    other_amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="3. Other")
    other_account_code = forms.CharField(max_length=32, required=False, label="Other account code",
        help_text="Required for Other. This account is credited; LedgerOS validates it when posting.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].label = "Amount received"
        self.fields["deposit_amount"].label = "2. Deposit"
        self.fields["deposit_amount"].help_text = "Enter 0 to pass these funds to Other."
        self.fields["invoice_amount"].help_text = "Includes late fees. Oldest open invoices first; enter 0 to skip."
        payment = self.instance if self.instance.pk else None
        self.can_allocate = not payment or (payment.status not in ("posted", "voided") and payment.is_editable_after_sync)
        if payment and payment.status not in ("posted", "voided") and payment.unapplied_amount > 0:
            self.can_allocate = not (payment.sync_record and payment.sync_record.attempt_count) and all(
                not obj or not obj.sync_record or not obj.sync_record.attempt_count
                for obj in (getattr(payment, "deposit_allocation", None), getattr(payment, "other_allocation", None))
            ) and all(not app.sync_record or not app.sync_record.attempt_count or (
                app.sync_record.status == "succeeded" and app.sync_record.ledgeros_journal_entry_id
            ) for app in payment.applications.select_related("sync_record"))
        if payment:
            if payment.allocation_reviewed or payment.applications.exists():
                self.fields["invoice_amount"].initial = payment.allocated_amount
            self.fields["other_amount"].initial = payment.other_amount
            other = getattr(payment, "other_allocation", None)
            if other:
                self.fields["other_account_code"].initial = other.account_code
            if self.can_allocate:
                for name in ("deposit_amount", "deposit_lease", "other_amount", "other_account_code"):
                    self.fields[name].disabled = False
            else:
                for name in self.fields:
                    if name != "notes":
                        self.fields[name].disabled = True
        self.order_fields(["property", "tenant", "payment_date", "amount", "payment_method", "reference", "notes",
                           "invoice_amount", "deposit_lease", "deposit_amount", "other_amount", "other_account_code", "status"])
        self.fields["status"].widget = forms.HiddenInput()
        self.preview = {"invoices": [], "leases": [], "invoice_due": "0.00"}
        property_id = self.data.get("property", getattr(payment, "property_id", None)) if self.is_bound else self.initial.get("property", getattr(payment, "property_id", None))
        tenant_id = self.data.get("tenant", getattr(payment, "tenant_id", None)) if self.is_bound else self.initial.get("tenant", getattr(payment, "tenant_id", None))
        if str(property_id).isdigit() and str(tenant_id).isdigit():
            self.preview = receipt_waterfall(property_id=property_id, tenant_id=tenant_id, payment=payment)
        self.fields["deposit_lease"].queryset = self.fields["deposit_lease"].queryset.filter(
            pk__in=[row["id"] for row in self.preview["leases"]])

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get("amount")
        invoice = cleaned.get("invoice_amount")
        deposit = cleaned.get("deposit_amount") or Decimal("0.00")
        other = cleaned.get("other_amount") or Decimal("0.00")
        if "invoice_amount" in self.data and invoice is None:
            self.add_error("invoice_amount", "Enter an allocation, including 0 to skip open invoices.")
        if invoice is not None and total is not None and invoice + deposit + other > total:
            self.add_error(None, "Allocations cannot exceed the amount received.")
        if other and not cleaned.get("other_account_code"):
            self.add_error("other_account_code", "Specify an account for Other.")
        return cleaned
