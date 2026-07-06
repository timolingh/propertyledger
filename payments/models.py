from __future__ import annotations

import builtins
from decimal import Decimal

from django.db import models

from ledgeros.models import LedgerOSSyncRecord, Property, Tenant, Unit, Lease, TenantCharge


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
        return not self.is_synced

    @builtins.property
    def is_synced(self) -> bool:
        return bool(self.sync_record and self.sync_record.is_successful)


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
        return not self.is_synced

    @builtins.property
    def is_synced(self) -> bool:
        return bool(self.sync_record and self.sync_record.is_successful)


class SecurityDepositEvent(models.Model):
    class EventType(models.TextChoices):
        REQUIRED = "required", "Required"
        RECEIVED = "received", "Received"
        DEDUCTED = "deducted", "Deducted"
        REFUNDED = "refunded", "Refunded"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
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

    @builtins.property
    def is_synced(self) -> bool:
        return bool(self.sync_record and self.sync_record.is_successful)

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return not self.is_synced
