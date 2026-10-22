from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ledgeros.audit import audit_success
from payments.authorization import require_maintenance_editor
from payments.models import MaintenanceRequest, MaintenanceRequestEvent


class MaintenanceRequestService:
    EDITABLE_FIELDS = (
        "property",
        "unit",
        "tenant",
        "category",
        "priority",
        "description",
        "assigned_vendor",
        "target_completion_date",
        "estimated_cost",
        "source",
        "source_reference",
    )

    TRANSITIONS = {
        "triage": ({MaintenanceRequest.Status.OPEN}, MaintenanceRequest.Status.TRIAGED),
        "assign": ({MaintenanceRequest.Status.TRIAGED}, MaintenanceRequest.Status.ASSIGNED),
        "start": ({MaintenanceRequest.Status.ASSIGNED}, MaintenanceRequest.Status.IN_PROGRESS),
        "verify": ({MaintenanceRequest.Status.IN_PROGRESS}, MaintenanceRequest.Status.VERIFIED),
        "close": ({MaintenanceRequest.Status.VERIFIED}, MaintenanceRequest.Status.CLOSED),
        "reopen": ({MaintenanceRequest.Status.CLOSED}, MaintenanceRequest.Status.TRIAGED),
        "cancel": (
            {
                MaintenanceRequest.Status.OPEN,
                MaintenanceRequest.Status.TRIAGED,
                MaintenanceRequest.Status.ASSIGNED,
                MaintenanceRequest.Status.IN_PROGRESS,
                MaintenanceRequest.Status.ON_HOLD,
            },
            MaintenanceRequest.Status.CANCELLED,
        ),
    }

    @classmethod
    @transaction.atomic
    def create(cls, *, actor, source=MaintenanceRequest.Source.INTERNAL, source_reference="", **fields):
        require_maintenance_editor(actor)
        request = MaintenanceRequest(
            **fields,
            source=source,
            source_reference=source_reference,
            created_by=actor,
            status=MaintenanceRequest.Status.OPEN,
            version=1,
        )
        request.full_clean()
        request.save()
        cls._record_event(
            request=request,
            action=MaintenanceRequestEvent.Action.CREATED,
            actor=actor,
            from_status="",
        )
        audit_success(action="maintenance_request.created", record=request, user=actor)
        return request

    @classmethod
    @transaction.atomic
    def update(cls, *, request, actor, expected_version: int):
        require_maintenance_editor(actor)
        current = MaintenanceRequest.objects.select_for_update().get(pk=request.pk)
        cls._require_version(current, expected_version)
        if current.status in {MaintenanceRequest.Status.CLOSED, MaintenanceRequest.Status.CANCELLED}:
            raise ValidationError("Closed or cancelled maintenance requests must be reopened before editing.")
        changes = {}
        for field in cls.EDITABLE_FIELDS:
            old_value = cls._audit_value(current, field)
            new_value = cls._audit_value(request, field)
            if old_value != new_value:
                changes[field] = {"from": old_value, "to": new_value}
            setattr(current, field, getattr(request, field))
        current.version += 1
        current.full_clean()
        current.save()
        cls._record_event(
            request=current,
            action=MaintenanceRequestEvent.Action.UPDATED,
            actor=actor,
            from_status=current.status,
            metadata={"changes": changes},
        )
        audit_success(
            action="maintenance_request.updated",
            record=current,
            user=actor,
            metadata={"version": current.version, "changes": changes},
        )
        return current

    @classmethod
    @transaction.atomic
    def transition(
        cls,
        *,
        request,
        action: str,
        actor,
        expected_version: int,
        reason: str = "",
        assigned_vendor=None,
        closure_financial_status: str = "",
    ):
        require_maintenance_editor(actor)
        current = MaintenanceRequest.objects.select_for_update().get(pk=request.pk)
        cls._require_version(current, expected_version)
        reason = (reason or "").strip()
        from_status = current.status

        if action == MaintenanceRequestEvent.Action.HOLD:
            if from_status not in {
                MaintenanceRequest.Status.TRIAGED,
                MaintenanceRequest.Status.ASSIGNED,
                MaintenanceRequest.Status.IN_PROGRESS,
            }:
                raise ValidationError("This maintenance request cannot be put on hold from its current state.")
            if not reason:
                raise ValidationError("A reason is required to put maintenance work on hold.")
            current.hold_from_status = from_status
            to_status = MaintenanceRequest.Status.ON_HOLD
        elif action == MaintenanceRequestEvent.Action.RESUME:
            if from_status != MaintenanceRequest.Status.ON_HOLD or current.hold_from_status not in {
                MaintenanceRequest.Status.TRIAGED,
                MaintenanceRequest.Status.ASSIGNED,
                MaintenanceRequest.Status.IN_PROGRESS,
            }:
                raise ValidationError("This maintenance request has no valid work state to resume.")
            to_status = current.hold_from_status
            current.hold_from_status = ""
        else:
            transition = cls.TRANSITIONS.get(action)
            if not transition or from_status not in transition[0]:
                raise ValidationError("That maintenance transition is not allowed from the current state.")
            to_status = transition[1]

        if action == MaintenanceRequestEvent.Action.ASSIGN:
            if assigned_vendor is not None:
                current.assigned_vendor = assigned_vendor
            if current.assigned_vendor_id is None:
                raise ValidationError("Assign a vendor before moving this request to Assigned.")
        if action == MaintenanceRequestEvent.Action.VERIFY:
            current.verified_by = actor
            current.verified_at = timezone.now()
        if action == MaintenanceRequestEvent.Action.CLOSE:
            valid_dispositions = set(MaintenanceRequest.ClosureFinancialStatus.values)
            if closure_financial_status not in valid_dispositions:
                raise ValidationError("Select whether a vendor invoice is pending or there is no external cost.")
            if not reason:
                raise ValidationError("A closure note is required.")
            current.closure_financial_status = closure_financial_status
            current.closure_notes = reason
            current.closed_by = actor
            current.closed_at = timezone.now()
        if action == MaintenanceRequestEvent.Action.REOPEN:
            if not reason:
                raise ValidationError("A reason is required to reopen maintenance work.")
            current.closed_by = None
            current.closed_at = None
            current.closure_financial_status = ""
            current.closure_notes = ""
            current.reopen_count += 1
        if action == MaintenanceRequestEvent.Action.CANCEL and not reason:
            raise ValidationError("A reason is required to cancel maintenance work.")

        current.status = to_status
        current.version += 1
        current.full_clean()
        current.save()
        event_metadata = {}
        if action == MaintenanceRequestEvent.Action.ASSIGN:
            event_metadata["assigned_vendor_id"] = current.assigned_vendor_id
        if action == MaintenanceRequestEvent.Action.CLOSE:
            event_metadata["closure_financial_status"] = closure_financial_status
        cls._record_event(
            request=current,
            action=action,
            actor=actor,
            from_status=from_status,
            reason=reason,
            metadata=event_metadata,
        )
        audit_success(
            action=f"maintenance_request.{action}",
            record=current,
            user=actor,
            metadata={"from_status": from_status, "to_status": to_status, "version": current.version},
        )
        return current

    @staticmethod
    def _require_version(request: MaintenanceRequest, expected_version: int) -> None:
        if request.version != expected_version:
            raise ValidationError(
                "This maintenance request changed after the page was loaded. Refresh and review the latest state."
            )

    @staticmethod
    def _record_event(*, request, action, actor, from_status, reason="", metadata=None):
        return MaintenanceRequestEvent.objects.create(
            request=request,
            action=action,
            from_status=from_status,
            to_status=request.status,
            actor=actor,
            reason=reason,
            request_version=request.version,
            metadata=metadata or {},
        )

    @staticmethod
    def _audit_value(request: MaintenanceRequest, field_name: str):
        field = request._meta.get_field(field_name)
        value = getattr(request, field.attname if field.is_relation else field_name)
        if isinstance(value, (date, Decimal)):
            return str(value)
        return value
