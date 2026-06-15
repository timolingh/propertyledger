from __future__ import annotations

from django.db import models


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
    client_id = models.CharField(max_length=255, blank=True)
    hmac_secret_env_var = models.CharField(
        max_length=255, default="LEDGEROS_HMAC_SECRET"
    )
    api_key_env_var = models.CharField(max_length=255, blank=True, default="")
    health_path = models.CharField(max_length=255, default="/health/")
    timeout_seconds = models.PositiveSmallIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LedgerOS connection settings"

    def __str__(self) -> str:
        return "LedgerOS connection settings"


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
