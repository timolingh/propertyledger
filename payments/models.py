from __future__ import annotations

import builtins
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from ledgeros.models import LedgerOSSyncRecord, Property, Tenant, Unit, Lease, TenantCharge, TimestampedModel
from ledgeros.models import PropertyLedgerAccountMapping, PropertyLedgerSetup


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
        POSTED = "posted", "Posted"
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
        if self.status == self.Status.POSTED or (
            self.sync_record and self.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
        ):
            return False
        # An unsuccessful response can still follow a committed upstream write.
        # Keep retry payloads stable once any allocation has been attempted.
        return not self.applications.filter(sync_record__attempt_count__gt=0).exists()

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""


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
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        POSTED = "posted", "Posted"
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
    def is_editable_after_sync(self) -> bool:
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""


class Vendor(TimestampedModel):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="vendor",
    )

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""


class MaintenanceCategory(TimestampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class MaintenanceRequest(TimestampedModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        TRIAGED = "triaged", "Triaged"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        ON_HOLD = "on_hold", "On hold"
        VERIFIED = "verified", "Verified"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    class Source(models.TextChoices):
        INTERNAL = "internal", "Internal staff"
        IMPORT = "import", "Imported"
        API = "api", "API"

    class ClosureFinancialStatus(models.TextChoices):
        INVOICE_PENDING = "invoice_pending", "Vendor invoice pending"
        NO_EXTERNAL_COST = "no_external_cost", "No external cost"

    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        blank=True,
        null=True,
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        blank=True,
        null=True,
    )
    category = models.ForeignKey(
        MaintenanceCategory,
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
    )
    assigned_vendor = models.ForeignKey(
        "Vendor",
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        blank=True,
        null=True,
    )
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    description = models.TextField()
    target_completion_date = models.DateField(blank=True, null=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.INTERNAL)
    source_reference = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    version = models.PositiveIntegerField(default=1)
    hold_from_status = models.CharField(max_length=20, choices=Status.choices, blank=True, default="")
    closure_financial_status = models.CharField(
        max_length=24,
        choices=ClosureFinancialStatus.choices,
        blank=True,
        default="",
    )
    closure_notes = models.TextField(blank=True, default="")
    reopen_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_maintenance_requests",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="verified_maintenance_requests",
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="closed_maintenance_requests",
    )
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "priority"], name="maint_req_status_priority"),
            models.Index(fields=["property", "status"], name="maint_req_property_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(estimated_cost__isnull=True) | models.Q(estimated_cost__gte=0),
                name="maintenance_estimated_cost_nonnegative",
            ),
            models.CheckConstraint(check=models.Q(version__gte=1), name="maintenance_version_positive"),
        ]

    def __str__(self) -> str:
        return f"Maintenance request {self.pk or 'new'} · {self.property}"

    def clean(self):
        super().clean()
        errors = {}
        if not self.description or not self.description.strip():
            errors["description"] = "Description is required."
        if self.estimated_cost is not None and self.estimated_cost < Decimal("0.00"):
            errors["estimated_cost"] = "Estimated cost cannot be negative."
        if self.unit_id and self.property_id and self.unit.property_id != self.property_id:
            errors["unit"] = "Unit must belong to the selected property."
        if self.tenant_id and self.property_id:
            leases = Lease.objects.filter(tenant_id=self.tenant_id, unit__property_id=self.property_id)
            if self.unit_id:
                leases = leases.filter(unit_id=self.unit_id)
            if not leases.exists():
                errors["tenant"] = "Tenant must have a lease associated with the selected property and unit."
        if errors:
            raise ValidationError(errors)


class MaintenanceRequestEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        TRIAGE = "triage", "Triaged"
        ASSIGN = "assign", "Assigned"
        START = "start", "Started"
        HOLD = "hold", "Put on hold"
        RESUME = "resume", "Resumed"
        VERIFY = "verify", "Verified"
        CLOSE = "close", "Closed"
        REOPEN = "reopen", "Reopened"
        CANCEL = "cancel", "Cancelled"

    request = models.ForeignKey(
        MaintenanceRequest,
        on_delete=models.PROTECT,
        related_name="events",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    from_status = models.CharField(max_length=20, choices=MaintenanceRequest.Status.choices, blank=True, default="")
    to_status = models.CharField(max_length=20, choices=MaintenanceRequest.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="maintenance_request_events",
    )
    reason = models.TextField(blank=True, default="")
    request_version = models.PositiveIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"Request {self.request_id}: {self.get_action_display()}"


class WorkflowAuthorization(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="propertyledger_workflow_authorization",
    )
    can_approve_vendor_bills = models.BooleanField(default=False)
    can_pay_vendor_bills = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="propertyledger_authorization_updates",
    )

    class Meta:
        ordering = ["user__username", "user_id"]

    def __str__(self) -> str:
        return f"Workflow authorization for {self.user}"


class VendorBill(TimestampedModel):
    class ExpenseCategory(models.TextChoices):
        REPAIRS_AND_MAINTENANCE = "repairs_and_maintenance", "Repairs and maintenance"
        UTILITIES = "utilities", "Utilities"
        MANAGEMENT_FEE = "management_fee", "Management fee"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        POSTED = "posted", "Posted"
        VOIDED = "voided", "Voided"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Awaiting approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        LEGACY_UNRECORDED = "legacy_unrecorded", "Legacy / approval not recorded"

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
    approval_status = models.CharField(
        max_length=24,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_vendor_bills",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="submitted_vendor_bills",
    )
    submitted_at = models.DateTimeField(blank=True, null=True)
    submission_version = models.PositiveIntegerField(default=0)
    approved_fingerprint = models.CharField(max_length=64, blank=True, default="")
    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="decided_vendor_bills",
    )
    decision_at = models.DateTimeField(blank=True, null=True)
    decision_reason = models.TextField(blank=True, default="")
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
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""

    def clean(self):
        super().clean()
        if self.unit_id and self.unit.property_id != self.property_id:
            raise ValidationError({"unit": "Unit must belong to the selected property."})


class VendorBillApprovalEvent(models.Model):
    bill = models.ForeignKey(
        VendorBill,
        on_delete=models.PROTECT,
        related_name="approval_events",
    )
    action = models.CharField(max_length=32, choices=VendorBill.ApprovalStatus.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="vendor_bill_approval_events",
    )
    submission_version = models.PositiveIntegerField(default=0)
    financial_fingerprint = models.CharField(max_length=64, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"Bill {self.bill_id}: {self.get_action_display()}"


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
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        POSTED = "posted", "Posted"
        VOIDED = "voided", "Voided"

    submission_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    submission_hash = models.CharField(max_length=64, blank=True, default="", editable=False)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="initiated_vendor_payments",
    )

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
        return self.sync_record is None or (
            self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED
            and self.sync_record.attempt_count == 0
        )

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""

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
            operating_bank_account_name = _operating_bank_account_name()
            if not self.bank_account_name.strip():
                raise ValidationError(
                    {"bank_account_name": "Bank account is required for non-credit-card payments."}
                )
            if self.bank_account_name.strip() != operating_bank_account_name:
                raise ValidationError(
                    {
                        "bank_account_name": (
                            f"Vendor payments must use the configured operating bank account: {operating_bank_account_name}."
                        )
                    }
                )


class DebtServicePayment(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        POSTED = "posted", "Posted"
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
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""

    def clean(self):
        super().clean()
        principal = self.principal_amount.quantize(Decimal("0.01"))
        interest = self.interest_amount.quantize(Decimal("0.01"))
        total = self.total_amount.quantize(Decimal("0.01"))
        if (principal + interest).quantize(Decimal("0.01")) != total:
            raise ValidationError(
                {"total_amount": "Principal plus interest must equal the total amount."}
            )
        if self.payment_account_name.strip():
            operating_bank_account_name = _operating_bank_account_name()
            if self.payment_account_name.strip() != operating_bank_account_name:
                raise ValidationError(
                    {
                        "payment_account_name": (
                            f"Debt-service payments must use the configured operating bank account: {operating_bank_account_name}."
                        )
                    }
                )


def _operating_bank_account_name() -> str:
    setup = PropertyLedgerSetup.load()
    mapping = setup.account_mappings.filter(
        mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT
    ).first()
    if mapping is None or not mapping.is_valid_for_completion:
        raise ValidationError(
            {
                "bank_account_name": (
                    "The operating bank account mapping is required and must be valid before this record can save."
                )
            }
        )
    account_name = mapping.ledgeros_account_name.strip()
    if not account_name:
        raise ValidationError(
            {
                "bank_account_name": (
                    "The operating bank account mapping must have a non-empty account name."
                )
            }
        )
    return account_name
