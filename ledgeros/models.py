from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


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


class LedgerOSConnectionSettings(SingletonModel):
    base_url = models.URLField(blank=True)
    host_header = models.CharField(max_length=255, blank=True, default="")
    client_id = models.CharField(max_length=255, blank=True)
    hmac_secret_env_var = models.CharField(
        max_length=255, default="LEDGEROS_HMAC_SECRET"
    )
    api_key_env_var = models.CharField(max_length=255, blank=True, default="")
    health_path = models.CharField(max_length=255, default="/api/v1/health/")
    timeout_seconds = models.PositiveSmallIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LedgerOS connection settings"

    def __str__(self) -> str:
        return "LedgerOS connection settings"


class PropertyLedgerSetup(SingletonModel):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        VALIDATED = "validated", "Validated"
        COMPLETE = "complete", "Complete"

    setup_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED
    )
    ledgeros_entity_id = models.CharField(max_length=255, blank=True, default="")
    ledgeros_entity_name = models.CharField(max_length=255, blank=True, default="")
    ledgeros_accounting_period_id = models.CharField(
        max_length=255, blank=True, default=""
    )
    ledgeros_accounting_period_name = models.CharField(
        max_length=255, blank=True, default=""
    )
    last_ledgeros_health_check_at = models.DateTimeField(blank=True, null=True)
    last_ledgeros_health_check_healthy = models.BooleanField(default=False)
    last_ledgeros_health_check_payload = models.JSONField(blank=True, null=True)
    last_setup_smoke_at = models.DateTimeField(blank=True, null=True)
    last_setup_smoke_healthy = models.BooleanField(default=False)
    last_setup_smoke_payload = models.JSONField(blank=True, null=True)
    validated_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    REQUIRED_ACCOUNT_MAPPING_KEYS = (
        "operating_bank_account",
        "undeposited_funds",
        "accounts_receivable",
        "accounts_payable",
        "rental_income",
        "repairs_and_maintenance_expense",
        "tenant_security_deposits_liability",
        "owner_contributions_equity",
        "owner_distributions_equity",
    )
    OPTIONAL_ACCOUNT_MAPPING_KEYS = (
        "credit_card_liability",
        "mortgage_or_loan_liability",
        "interest_expense",
        "principal_payment_mapping",
    )
    SETUP_ERROR_LABELS = {
        "ledgeros_health": "LedgerOS health",
        "ledgeros_entity": "LedgerOS entity",
        "accounting_period": "Accounting period",
        "required_account_mappings": "Required account mappings",
        "optional_account_mappings": "Optional account mappings",
        "setup_smoke": "Setup smoke",
    }

    class Meta:
        verbose_name = "PropertyLedger setup"

    def __str__(self) -> str:
        return "PropertyLedger setup"

    @property
    def has_selected_ledgeros_entity(self) -> bool:
        return bool(self.ledgeros_entity_id and self.ledgeros_entity_name)

    @property
    def has_selected_accounting_period(self) -> bool:
        return bool(
            self.ledgeros_accounting_period_id
            and self.ledgeros_accounting_period_name
        )

    def _mapping_by_key(self) -> dict[str, "PropertyLedgerAccountMapping"]:
        return {
            mapping.mapping_key: mapping for mapping in self.account_mappings.all()
        }

    def missing_required_account_mappings(self) -> list[str]:
        mappings = self._mapping_by_key()
        missing = []
        for mapping_key in self.REQUIRED_ACCOUNT_MAPPING_KEYS:
            mapping = mappings.get(mapping_key)
            if mapping is None or not mapping.is_valid_for_completion:
                missing.append(mapping_key)
        return missing

    def invalid_enabled_optional_account_mappings(self) -> list[str]:
        mappings = self._mapping_by_key()
        invalid = []
        for mapping_key in self.OPTIONAL_ACCOUNT_MAPPING_KEYS:
            mapping = mappings.get(mapping_key)
            if (
                mapping is not None
                and mapping.is_enabled
                and not mapping.is_valid_for_completion
            ):
                invalid.append(mapping_key)
        return invalid

    def setup_completion_errors(self) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        if not self.last_ledgeros_health_check_healthy:
            errors["ledgeros_health"] = [
                "LedgerOS health must succeed before setup can be complete."
            ]
        if not self.has_selected_ledgeros_entity:
            errors["ledgeros_entity"] = ["A LedgerOS entity must be selected."]
        if not self.has_selected_accounting_period:
            errors["accounting_period"] = [
                "An open accounting period must be selected."
            ]

        missing_required = self.missing_required_account_mappings()
        if missing_required:
            errors["required_account_mappings"] = [
                f"Missing or invalid mapping: {mapping_key}"
                for mapping_key in missing_required
            ]

        invalid_optional = self.invalid_enabled_optional_account_mappings()
        if invalid_optional:
            errors["optional_account_mappings"] = [
                f"Missing or invalid enabled optional mapping: {mapping_key}"
                for mapping_key in invalid_optional
            ]

        if not self.last_setup_smoke_healthy:
            errors["setup_smoke"] = [
                "Setup smoke validation must succeed before setup can be complete."
            ]

        return errors

    def setup_completion_error_groups(self) -> list[dict[str, list[str] | str]]:
        errors = self.setup_completion_errors()
        return [
            {
                "label": self.SETUP_ERROR_LABELS.get(
                    field, field.replace("_", " ").title()
                ),
                "messages": messages,
            }
            for field, messages in errors.items()
        ]

    def clean(self):
        super().clean()
        if self.setup_status in {
            self.Status.VALIDATED,
            self.Status.COMPLETE,
        }:
            errors = self.setup_completion_errors()
            if self.setup_status == self.Status.VALIDATED:
                errors.pop("setup_smoke", None)
            if errors:
                raise ValidationError(errors)


class PropertyLedgerAccountMapping(models.Model):
    class MappingKey(models.TextChoices):
        OPERATING_BANK_ACCOUNT = "operating_bank_account", "Operating bank account"
        UNDEPOSITED_FUNDS = "undeposited_funds", "Undeposited funds"
        ACCOUNTS_RECEIVABLE = "accounts_receivable", "Accounts receivable"
        ACCOUNTS_PAYABLE = "accounts_payable", "Accounts payable"
        RENTAL_INCOME = "rental_income", "Rental income"
        REPAIRS_AND_MAINTENANCE_EXPENSE = (
            "repairs_and_maintenance_expense",
            "Repairs and maintenance expense",
        )
        TENANT_SECURITY_DEPOSITS_LIABILITY = (
            "tenant_security_deposits_liability",
            "Tenant security deposits liability",
        )
        OWNER_CONTRIBUTIONS_EQUITY = (
            "owner_contributions_equity",
            "Owner contributions equity",
        )
        OWNER_DISTRIBUTIONS_EQUITY = (
            "owner_distributions_equity",
            "Owner distributions equity",
        )
        CREDIT_CARD_LIABILITY = "credit_card_liability", "Credit card liability"
        MORTGAGE_OR_LOAN_LIABILITY = (
            "mortgage_or_loan_liability",
            "Mortgage or loan liability",
        )
        INTEREST_EXPENSE = "interest_expense", "Interest expense"
        PRINCIPAL_PAYMENT_MAPPING = (
            "principal_payment_mapping",
            "Principal payment mapping",
        )

    ACCOUNT_TYPE_HINTS: dict[str, set[str]] = {
        MappingKey.OPERATING_BANK_ACCOUNT: {"asset", "cash", "bank"},
        MappingKey.UNDEPOSITED_FUNDS: {"asset", "clearing"},
        MappingKey.ACCOUNTS_RECEIVABLE: {"asset", "receivable", "ar"},
        MappingKey.ACCOUNTS_PAYABLE: {"liability", "payable", "ap"},
        MappingKey.RENTAL_INCOME: {"revenue", "income"},
        MappingKey.REPAIRS_AND_MAINTENANCE_EXPENSE: {"expense"},
        MappingKey.TENANT_SECURITY_DEPOSITS_LIABILITY: {"liability"},
        MappingKey.OWNER_CONTRIBUTIONS_EQUITY: {"equity"},
        MappingKey.OWNER_DISTRIBUTIONS_EQUITY: {"equity"},
        MappingKey.CREDIT_CARD_LIABILITY: {"liability"},
        MappingKey.MORTGAGE_OR_LOAN_LIABILITY: {"liability"},
        MappingKey.INTEREST_EXPENSE: {"expense"},
        MappingKey.PRINCIPAL_PAYMENT_MAPPING: {"liability"},
    }

    setup = models.ForeignKey(
        PropertyLedgerSetup,
        on_delete=models.CASCADE,
        related_name="account_mappings",
    )
    mapping_key = models.CharField(max_length=64, choices=MappingKey.choices)
    ledgeros_account_id = models.CharField(max_length=255, blank=True, default="")
    ledgeros_account_name = models.CharField(max_length=255, blank=True, default="")
    ledgeros_account_type = models.CharField(max_length=64, blank=True, default="")
    is_required = models.BooleanField(default=True)
    is_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("setup", "mapping_key")]
        ordering = ["mapping_key", "id"]

    def __str__(self) -> str:
        return self.get_mapping_key_display()

    @property
    def is_valid_for_completion(self) -> bool:
        if not self.ledgeros_account_id or not self.ledgeros_account_type:
            return False

        allowed_types = self.ACCOUNT_TYPE_HINTS.get(self.mapping_key)
        if not allowed_types:
            return True

        account_type = self.ledgeros_account_type.strip().lower()
        return account_type in allowed_types


class TimestampedModel(models.Model):
    class Meta:
        abstract = True

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Owner(TimestampedModel):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class Property(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=255)
    primary_owner = models.ForeignKey(
        Owner,
        on_delete=models.PROTECT,
        related_name="primary_properties",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name", "id"]
        verbose_name_plural = "Properties"

    def __str__(self) -> str:
        return self.name


class Unit(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="units",
    )
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["property__name", "name", "id"]
        unique_together = [("property", "name")]

    def __str__(self) -> str:
        return f"{self.property.name} / {self.name}"


class Tenant(TimestampedModel):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class Lease(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="leases",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="leases",
    )
    lease_start_date = models.DateField()
    lease_end_date = models.DateField(blank=True, null=True)
    rent_effective_date = models.DateField(blank=True, null=True)
    base_monthly_rent_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    deposit_required_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-lease_start_date", "-id"]

    def save(self, *args, **kwargs):  # type: ignore[override]
        if self.rent_effective_date is None:
            self.rent_effective_date = self.lease_start_date
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.unit} - {self.tenant}"


class TenantCharge(TimestampedModel):
    class ChargeType(models.TextChoices):
        BASE_RENT = "base_rent", "Base rent"
        UTILITY_REIMBURSEMENT = "utility_reimbursement", "Utility reimbursement"
        LATE_FEE_MANUAL = "late_fee_manual", "Late fee manual"
        OTHER_MANUAL = "other_manual", "Other manual"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        VOIDED = "voided", "Voided"

    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="tenant_charges",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="tenant_charges",
        blank=True,
        null=True,
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="tenant_charges",
        blank=True,
        null=True,
    )
    lease = models.ForeignKey(
        Lease,
        on_delete=models.PROTECT,
        related_name="tenant_charges",
        blank=True,
        null=True,
    )
    charge_type = models.CharField(max_length=64, choices=ChargeType.choices)
    billing_period_start = models.DateField(blank=True, null=True)
    billing_period_end = models.DateField(blank=True, null=True)
    charge_date = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    sync_record = models.OneToOneField(
        "LedgerOSSyncRecord",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tenant_charge",
    )

    class Meta:
        ordering = ["-charge_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["lease", "billing_period_start", "billing_period_end"],
                condition=Q(charge_type="base_rent"),
                name="uniq_base_rent_charge_period",
            )
        ]

    def clean(self):
        super().clean()
        if self.lease_id:
            self.property = self.lease.unit.property
            self.unit = self.lease.unit
            self.tenant = self.lease.tenant
            if self.charge_type == self.ChargeType.BASE_RENT:
                if not self.billing_period_start or not self.billing_period_end:
                    raise ValidationError(
                        {
                            "billing_period_start": "Billing period is required for base rent.",
                            "billing_period_end": "Billing period is required for base rent.",
                        }
                    )
            return

        if not self.property_id:
            raise ValidationError({"property": "Property is required."})

        if self.charge_type == self.ChargeType.BASE_RENT:
            raise ValidationError({"lease": "Base rent charges require a lease."})

    def clean_fields(self, exclude=None):
        exclude_set = set(exclude or [])
        if self.lease_id:
            exclude_set.update({"property", "unit", "tenant"})
        super().clean_fields(exclude=exclude_set)

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return not self.is_synced

    @builtins.property
    def is_synced(self) -> bool:
        return bool(self.sync_record and self.sync_record.is_successful)

    def get_charge_scope_summary(self) -> str:
        if self.lease_id:
            return f"{self.property.name} / {self.unit.name} -> {self.tenant.name}"
        if self.unit_id and self.tenant_id:
            return f"{self.property.name} / {self.unit.name} -> {self.tenant.name}"
        return self.property.name

    @classmethod
    def prorated_amount_for_period(
        cls,
        *,
        monthly_amount: Decimal,
        period_start: date,
        period_end: date,
        occupied_start: date,
        occupied_end: date | None = None,
    ) -> Decimal:
        occupied_end = occupied_end or period_end
        effective_start = max(period_start, occupied_start)
        effective_end = min(period_end, occupied_end)
        if effective_end < effective_start:
            return Decimal("0.00")
        days_in_period = (period_end - period_start).days + 1
        occupied_days = (effective_end - effective_start).days + 1
        prorated = (monthly_amount * Decimal(occupied_days)) / Decimal(days_in_period)
        return prorated.quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.get_charge_type_display()} | {self.property.name}"


class LedgerOSSyncRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        DUPLICATE = "duplicate", "Duplicate"
        CANCELLED = "cancelled", "Cancelled"

    local_object_type = models.CharField(max_length=255)
    local_object_id = models.CharField(max_length=255)
    ledgeros_resource_type = models.CharField(max_length=255)
    ledgeros_resource_id = models.CharField(
        max_length=255, blank=True, null=True
    )
    ledgeros_journal_entry_id = models.CharField(
        max_length=255, blank=True, null=True
    )
    source_event_type = models.CharField(max_length=255)
    external_id = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    response_payload = models.JSONField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    last_error = models.TextField(blank=True, null=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["local_object_type", "local_object_id", "source_event_type"],
                name="ledgeros_sync_record_local_object_source_unique",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                name="ledgeros_sync_record_idempotency_key_unique",
            ),
            models.UniqueConstraint(
                fields=["external_id", "source_event_type"],
                name="ledgeros_sync_record_external_id_source_unique",
            ),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.local_object_type}:{self.local_object_id} ({self.source_event_type})"

    @builtins.property
    def is_successful(self) -> bool:
        return self.status == self.Status.SUCCEEDED
