from __future__ import annotations

from rest_framework import serializers

from ledgeros.models import LedgerOSSyncRecord


class LedgerOSSyncRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerOSSyncRecord
        fields = [
            "id",
            "local_object_type",
            "local_object_id",
            "ledgeros_resource_type",
            "ledgeros_resource_id",
            "ledgeros_journal_entry_id",
            "source_event_type",
            "external_id",
            "idempotency_key",
            "request_hash",
            "response_payload",
            "status",
            "last_error",
            "attempt_count",
            "last_synced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
