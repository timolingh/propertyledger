from __future__ import annotations

from typing import Any

from ledgeros.models import AuditLog


def audit_success(
    *,
    action: str,
    record,
    user=None,
    source: str = "ui",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        action=action,
        actor=user if getattr(user, "is_authenticated", False) else None,
        record_type=record.__class__.__name__,
        record_id=str(record.pk),
        source=source,
        outcome=AuditLog.Outcome.SUCCESS,
        metadata=metadata or {},
    )


def audit_failure(
    *,
    action: str,
    record_type: str,
    record_id: str,
    user=None,
    source: str = "ui",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        action=action,
        actor=user if getattr(user, "is_authenticated", False) else None,
        record_type=record_type,
        record_id=record_id,
        source=source,
        outcome=AuditLog.Outcome.FAILURE,
        metadata=metadata or {},
    )
