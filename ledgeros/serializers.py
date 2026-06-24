from __future__ import annotations

from rest_framework import serializers


class LedgerOSSyncEventSerializer(serializers.Serializer):
    source_system = serializers.CharField()
    domain_event_type = serializers.CharField()
    external_id = serializers.CharField()
    source_object_type = serializers.CharField()
    source_object_id = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    payload = serializers.JSONField()

    def validate_source_system(self, value: str) -> str:
        if value != "propertyledger":
            raise serializers.ValidationError("source_system must be 'propertyledger'.")
        return value
