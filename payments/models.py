from __future__ import annotations

import builtins
from decimal import Decimal

from django.db import models
from django.core.exceptions import ValidationError

from ledgeros.models import LedgerOSSyncRecord, Property, Tenant, Unit, Lease, TenantCharge, TimestampedModel


def default_charge_type_priority() -> list[str]:
    return [
        TenantCharge.ChargeType.BASE_RENT,
        TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
        TenantCharge.ChargeType.LATE_FEE_MANUAL,
        TenantCharge.ChargeType.OTHER_MANUAL,
    ]


class SingletonModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):  # type: ignore[override]
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PaymentWorkflowSettings(SingletonModel):
    class Meta:
        verbose_name = "Payment workflow settings"

    charge_type_priority = models.JSONField(
        default=default_charge_type_priority,
        blank=True,
        help_text="Global charge allocation priority list for MVP.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TenantPayment(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CHECK = "check", "Check"
        ACH_MANUAL = "ach_manual", "ACH manual"
        CARD_MANUAL = "card_manual", "Card manual"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ALLOCATED = "allocated", "Allocated"
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        SYNC_PENDING = "sync_pending", "Sync pending"
        SYNCED = "synced", "Synced"
        SYNC_FAILED = "sync_failed", "Sync failed"
        VOIDED = "voided", "Voided"

    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="tenant_payments",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="tenant_payments",
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=32, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tenant_payment",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self) -> str:
        return f"{self.tenant} payment on {self.payment_date.isoformat()}"

    @builtins.property
    def allocated_amount(self) -> Decimal:
        total = self.applications.aggregate(total=models.Sum("amount_applied"))["total"]
        return (total or Decimal("0.00")).quantize(Decimal("0.01"))

    @builtins.property
    def remaining_amount(self) -> Decimal:
        return (self.amount - self.allocated_amount).quantize(Decimal("0.01"))

    @builtins.property
    def unapplied_amount(self) -> Decimal:
        return self.remaining_amount

    @builtins.property
    def is_credit_balance(self) -> bool:
        return self.remaining_amount > Decimal("0.00")

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.status != self.Status.SYNCED


class TenantPaymentApplication(models.Model):
    payment = models.ForeignKey(
        TenantPayment,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    charge = models.ForeignKey(
        TenantCharge,
        on_delete=models.PROTECT,
        related_name="payment_applications",
    )
    amount_applied = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tenant_payment_application",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["charge__due_date", "charge__charge_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "charge"],
                name="uniq_tenant_payment_application_charge",
            )
        ]

    def __str__(self) -> str:
        return f"{self.payment_id} -> {self.charge_id}"

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED


class SecurityDepositEvent(models.Model):
    class EventType(models.TextChoices):
        REQUIRED = "required", "Required"
        RECEIVED = "received", "Received"
        DEDUCTED = "deducted", "Deducted"
        REFUNDED = "refunded", "Refunded"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SYNC_PENDING = "sync_pending", "Sync pending"
        SYNCED = "synced", "Synced"
        SYNC_FAILED = "sync_failed", "Sync failed"
        VOIDED = "voided", "Voided"

    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="security_deposit_events",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="security_deposit_events",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="security_deposit_events",
    )
    lease = models.ForeignKey(
        Lease,
        on_delete=models.PROTECT,
        related_name="security_deposit_events",
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    event_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    description = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="security_deposit_event",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-id"]

    def __str__(self) -> str:
        return f"{self.tenant} {self.get_event_type_display()} on {self.event_date.isoformat()}"


class Vendor(TimestampedModel):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class MaintenanceCategory(TimestampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class VendorBill(TimestampedModel):
    class ExpenseCategory(models.TextChoices):
        REPAIRS_AND_MAINTENANCE = "repairs_and_maintenance", "Repairs and maintenance"
        UTILITIES = "utilities", "Utilities"
        MANAGEMENT_FEE = "management_fee", "Management fee"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SYNC_PENDING = "sync_pending", "Sync pending"
        SYNCED = "synced", "Synced"
        SYNC_FAILED = "sync_failed", "Sync failed"
        VOIDED = "voided", "Voided"

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="bills",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="vendor_bills",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="vendor_bills",
        blank=True,
        null=True,
    )
    bill_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    expense_category = models.CharField(max_length=64, choices=ExpenseCategory.choices)
    maintenance_category = models.ForeignKey(
        MaintenanceCategory,
        on_delete=models.PROTECT,
        related_name="vendor_bills",
        blank=True,
        null=True,
    )
    repair_notes = models.TextField(blank=True, default="")
    tenant_chargeable = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="vendor_bill",
    )

    class Meta:
        ordering = ["-bill_date", "-id"]

    def __str__(self) -> str:
        return f"{self.vendor} bill on {self.bill_date.isoformat()}"

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.status != self.Status.SYNCED

    def clean(self):
        super().clean()
        if self.unit_id and self.unit.property_id != self.property_id:
            raise ValidationError({"unit": "Unit must belong to the selected property."})


class VendorPayment(TimestampedModel):
    class PaymentMethod(models.TextChoices):
        MANUAL_CHECK = "manual_check", "Manual check"
        ACH_MANUAL = "ach_manual", "ACH manual"
        CREDIT_CARD = "credit_card", "Credit card"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    class CheckStatus(models.TextChoices):
        NOT_APPLICABLE = "not_applicable", "Not applicable"
        PENDING_PRINT = "pending_print", "Pending print"
        PRINTED = "printed", "Printed"
        VOIDED = "voided", "Voided"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SYNC_PENDING = "sync_pending", "Sync pending"
        SYNCED = "synced", "Synced"
        SYNC_FAILED = "sync_failed", "Sync failed"
        VOIDED = "voided", "Voided"

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    vendor_bill = models.ForeignKey(
        VendorBill,
        on_delete=models.PROTECT,
        related_name="vendor_payments",
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=32, choices=PaymentMethod.choices)
    bank_account_name = models.CharField(max_length=255, blank=True, default="")
    credit_card_account_name = models.CharField(max_length=255, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    check_number = models.CharField(max_length=64, blank=True, null=True)
    check_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_APPLICABLE,
    )
    is_credit_card_payoff = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="vendor_payment",
    )

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self) -> str:
        return f"{self.vendor} payment on {self.payment_date.isoformat()}"

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.status != self.Status.SYNCED

    def clean(self):
        super().clean()
        if self.vendor_bill_id and self.vendor_bill.vendor_id != self.vendor_id:
            raise ValidationError({"vendor_bill": "Vendor payment vendor must match the selected bill vendor."})
        if self.is_credit_card_payoff and self.payment_method == self.PaymentMethod.CREDIT_CARD:
            raise ValidationError(
                {"payment_method": "Credit card payoffs cannot also use credit card payment method."}
            )
        if self.is_credit_card_payoff and not self.bank_account_name.strip():
            raise ValidationError(
                {"bank_account_name": "Bank account is required for credit card payoffs."}
            )
        if self.payment_method == self.PaymentMethod.CREDIT_CARD:
            if not self.credit_card_account_name.strip():
                raise ValidationError(
                    {"credit_card_account_name": "Credit card account is required for credit card payments."}
                )
        else:
            if not self.bank_account_name.strip():
                raise ValidationError(
                    {"bank_account_name": "Bank account is required for non-credit-card payments."}
                )


class DebtServicePayment(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SYNC_PENDING = "sync_pending", "Sync pending"
        SYNCED = "synced", "Synced"
        SYNC_FAILED = "sync_failed", "Sync failed"
        VOIDED = "voided", "Voided"

    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="debt_service_payments",
    )
    lender = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="debt_service_payments",
    )
    payment_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    interest_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_account_name = models.CharField(max_length=255, blank=True, default="")
    loan_liability_account_name = models.CharField(max_length=255, blank=True, default="")
    interest_expense_account_name = models.CharField(max_length=255, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="debt_service_payment",
    )

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self) -> str:
        return f"{self.lender} debt service on {self.payment_date.isoformat()}"

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.status != self.Status.SYNCED

    def clean(self):
        super().clean()
        principal = self.principal_amount.quantize(Decimal("0.01"))
        interest = self.interest_amount.quantize(Decimal("0.01"))
        total = self.total_amount.quantize(Decimal("0.01"))
        if (principal + interest).quantize(Decimal("0.01")) != total:
            raise ValidationError(
                {"total_amount": "Principal plus interest must equal the total amount."}
            )
