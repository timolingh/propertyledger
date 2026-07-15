from __future__ import annotations

import builtins
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from ledgeros.models import LedgerOSSyncRecord, Owner, Property, TimestampedModel


class OwnerContributionDistribution(TimestampedModel):
    class EventType(models.TextChoices):
        CONTRIBUTION = "contribution", "Contribution"
        DISTRIBUTION = "distribution", "Distribution"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY_TO_SYNC = "ready_to_sync", "Ready to sync"
        POSTED = "posted", "Posted"
        VOIDED = "voided", "Voided"

    owner = models.ForeignKey(
        Owner,
        on_delete=models.PROTECT,
        related_name="owner_activity_records",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="owner_activity_records",
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    event_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_account_name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sync_record = models.OneToOneField(
        LedgerOSSyncRecord,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="owner_activity_record",
    )

    class Meta:
        ordering = ["-event_date", "-id"]

    def __str__(self) -> str:
        return f"{self.owner} {self.get_event_type_display()} on {self.event_date.isoformat()}"

    def clean(self):
        super().clean()
        if self.property_id and self.owner_id and self.property.primary_owner_id != self.owner_id:
            raise ValidationError(
                {"owner": "The owner must match the property's primary owner for Epic 7 statements."}
            )
        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Amount must be non-negative."})

    @builtins.property
    def is_editable_after_sync(self) -> bool:
        return self.sync_record is None or self.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED

    @builtins.property
    def sync_status(self) -> str:
        return self.sync_record.status if self.sync_record else ""
