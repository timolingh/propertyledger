from __future__ import annotations

import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from ledgeros.audit import audit_success
from ledgeros.roles import ROLE_ADMIN, user_has_any_role
from payments.authorization import (
    WORKFLOW_FINANCIAL_ROLES,
    require_bill_approver,
    require_bill_editor,
    require_grant_administrator,
)
from payments.models import WorkflowAuthorization, VendorBill, VendorBillApprovalEvent


class WorkflowAuthorizationService:
    @staticmethod
    @transaction.atomic
    def set_grants(
        *,
        target,
        actor,
        can_approve_vendor_bills: bool,
        can_pay_vendor_bills: bool,
        source: str = "ui",
    ) -> WorkflowAuthorization:
        require_grant_administrator(actor)
        if (can_approve_vendor_bills or can_pay_vendor_bills) and not user_has_any_role(
            target, WORKFLOW_FINANCIAL_ROLES
        ):
            raise ValidationError(
                "Approval and payment grants require an active administrator, property manager, or bookkeeper role."
            )
        authorization, _ = WorkflowAuthorization.objects.select_for_update().get_or_create(user=target)
        old_values = {
            "can_approve_vendor_bills": authorization.can_approve_vendor_bills,
            "can_pay_vendor_bills": authorization.can_pay_vendor_bills,
        }
        authorization.can_approve_vendor_bills = bool(can_approve_vendor_bills)
        authorization.can_pay_vendor_bills = bool(can_pay_vendor_bills)
        authorization.updated_by = actor
        authorization.save()
        audit_success(
            action="workflow_authorization_updated",
            record=authorization,
            user=actor,
            source=source,
            metadata={
                "target_user_id": target.pk,
                "old": old_values,
                "new": {
                    "can_approve_vendor_bills": authorization.can_approve_vendor_bills,
                    "can_pay_vendor_bills": authorization.can_pay_vendor_bills,
                },
            },
        )
        return authorization


class VendorBillApprovalService:
    FINANCIAL_FIELDS = (
        "vendor_invoice_number",
        "vendor_id",
        "property_id",
        "unit_id",
        "bill_date",
        "due_date",
        "amount",
        "expense_category",
        "maintenance_category_id",
        "repair_notes",
        "tenant_chargeable",
    )
    EDITABLE_FIELDS = (
        "vendor_invoice_number",
        "vendor_id",
        "property_id",
        "unit_id",
        "bill_date",
        "due_date",
        "amount",
        "expense_category",
        "maintenance_category_id",
        "repair_notes",
        "tenant_chargeable",
        "notes",
    )

    @staticmethod
    def financial_fingerprint(bill: VendorBill) -> str:
        values = {}
        for field in VendorBillApprovalService.FINANCIAL_FIELDS:
            value = getattr(bill, field)
            # Preserve existing approvals for bills predating invoice references.
            if field == "vendor_invoice_number" and not value:
                continue
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif value is not None:
                value = str(value)
            values[field] = value
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _event(bill: VendorBill, *, action: str, actor, reason: str = "") -> None:
        fingerprint = VendorBillApprovalService.financial_fingerprint(bill)
        VendorBillApprovalEvent.objects.create(
            bill=bill,
            action=action,
            actor=actor,
            submission_version=bill.submission_version,
            financial_fingerprint=fingerprint,
            reason=reason,
        )
        audit_success(
            action=f"vendor_bill_{action}",
            record=bill,
            user=actor,
            source="service",
            metadata={
                "submission_version": bill.submission_version,
                "financial_fingerprint": fingerprint,
                "reason": reason,
            },
        )

    @staticmethod
    @transaction.atomic
    def save_draft(bill: VendorBill, *, actor) -> VendorBill:
        require_bill_editor(actor)
        if not bill.pk:
            bill.apply_date_defaults()
        bill.full_clean()
        if not bill.pk:
            bill.created_by = actor
            bill.approval_status = VendorBill.ApprovalStatus.DRAFT
            bill.save()
            return bill

        current = VendorBill.objects.select_for_update().get(pk=bill.pk)
        if current.approval_status == VendorBill.ApprovalStatus.SUBMITTED:
            raise ValidationError("Withdraw or reject this submitted bill before editing it.")
        changed_financial = any(
            getattr(current, field) != getattr(bill, field)
            for field in VendorBillApprovalService.FINANCIAL_FIELDS
        )
        if current.status == VendorBill.Status.POSTED and changed_financial:
            raise ValidationError("Posted vendor bill accounting fields cannot be changed.")
        for field in VendorBillApprovalService.EDITABLE_FIELDS:
            setattr(current, field, getattr(bill, field))
        if current.approval_status in {
            VendorBill.ApprovalStatus.APPROVED,
            VendorBill.ApprovalStatus.REJECTED,
            VendorBill.ApprovalStatus.WITHDRAWN,
        } and changed_financial:
            current.approval_status = VendorBill.ApprovalStatus.DRAFT
            current.approved_fingerprint = ""
            current.decision_by = None
            current.decision_at = None
            current.decision_reason = ""
        current.full_clean()
        current.save()
        return current

    @staticmethod
    @transaction.atomic
    def submit(bill: VendorBill, *, actor) -> VendorBill:
        require_bill_editor(actor)
        bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
        if bill.approval_status not in {
            VendorBill.ApprovalStatus.DRAFT,
            VendorBill.ApprovalStatus.REJECTED,
            VendorBill.ApprovalStatus.WITHDRAWN,
            VendorBill.ApprovalStatus.LEGACY_UNRECORDED,
        }:
            raise ValidationError("Only a draft, rejected, withdrawn, or legacy bill can be submitted.")
        bill.full_clean()
        bill.approval_status = VendorBill.ApprovalStatus.SUBMITTED
        bill.submitted_by = actor
        bill.submitted_at = timezone.now()
        bill.submission_version += 1
        bill.approved_fingerprint = ""
        bill.decision_by = None
        bill.decision_at = None
        bill.decision_reason = ""
        bill.save()
        VendorBillApprovalService._event(
            bill, action=VendorBill.ApprovalStatus.SUBMITTED, actor=actor
        )
        return bill

    @staticmethod
    @transaction.atomic
    def withdraw(bill: VendorBill, *, actor, reason: str = "") -> VendorBill:
        require_bill_editor(actor)
        bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
        if bill.approval_status != VendorBill.ApprovalStatus.SUBMITTED:
            raise ValidationError("Only a submitted bill can be withdrawn.")
        if bill.submitted_by_id != actor.pk and not user_has_any_role(actor, (ROLE_ADMIN,)):
            raise PermissionDenied("Only the submitter or an administrator can withdraw this bill.")
        bill.approval_status = VendorBill.ApprovalStatus.WITHDRAWN
        bill.decision_by = actor
        bill.decision_at = timezone.now()
        bill.decision_reason = reason.strip()
        bill.save()
        VendorBillApprovalService._event(
            bill, action=VendorBill.ApprovalStatus.WITHDRAWN, actor=actor, reason=reason.strip()
        )
        return bill

    @staticmethod
    @transaction.atomic
    def approve(bill: VendorBill, *, actor, reason: str = "") -> VendorBill:
        require_bill_approver(actor)
        bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
        if bill.approval_status != VendorBill.ApprovalStatus.SUBMITTED:
            raise ValidationError("Only a submitted bill can be approved.")
        if bill.submitted_by_id == actor.pk:
            raise PermissionDenied("A vendor bill submitter cannot approve the same bill.")
        bill.approval_status = VendorBill.ApprovalStatus.APPROVED
        bill.approved_fingerprint = VendorBillApprovalService.financial_fingerprint(bill)
        bill.decision_by = actor
        bill.decision_at = timezone.now()
        bill.decision_reason = reason.strip()
        bill.save()
        VendorBillApprovalService._event(
            bill, action=VendorBill.ApprovalStatus.APPROVED, actor=actor, reason=reason.strip()
        )
        return bill

    @staticmethod
    @transaction.atomic
    def reject(bill: VendorBill, *, actor, reason: str) -> VendorBill:
        require_bill_approver(actor)
        reason = reason.strip()
        if not reason:
            raise ValidationError("A rejection reason is required.")
        bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
        if bill.approval_status != VendorBill.ApprovalStatus.SUBMITTED:
            raise ValidationError("Only a submitted bill can be rejected.")
        if bill.submitted_by_id == actor.pk:
            raise PermissionDenied("A vendor bill submitter cannot reject the same bill.")
        bill.approval_status = VendorBill.ApprovalStatus.REJECTED
        bill.approved_fingerprint = ""
        bill.decision_by = actor
        bill.decision_at = timezone.now()
        bill.decision_reason = reason
        bill.save()
        VendorBillApprovalService._event(
            bill, action=VendorBill.ApprovalStatus.REJECTED, actor=actor, reason=reason
        )
        return bill

    @staticmethod
    def approval_blocker(bill: VendorBill) -> str:
        if bill.approval_status != VendorBill.ApprovalStatus.APPROVED:
            return "The bill must be explicitly approved before it can be posted or paid."
        if bill.approved_fingerprint != VendorBillApprovalService.financial_fingerprint(bill):
            return "The approved bill details have changed and require reapproval."
        return ""
