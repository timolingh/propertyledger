from __future__ import annotations

from django.core.exceptions import PermissionDenied

from ledgeros.roles import (
    ROLE_ADMIN,
    ROLE_BOOKKEEPER,
    ROLE_PROPERTY_MANAGER,
    ROLE_READ_ONLY_VIEWER,
    user_has_any_role,
)
from payments.models import WorkflowAuthorization


WORKFLOW_FINANCIAL_ROLES = (ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER)
BILL_EDITOR_ROLES = (ROLE_ADMIN, ROLE_BOOKKEEPER)
MAINTENANCE_EDITOR_ROLES = (ROLE_ADMIN, ROLE_PROPERTY_MANAGER, ROLE_BOOKKEEPER)
MAINTENANCE_VIEWER_ROLES = (*MAINTENANCE_EDITOR_ROLES, ROLE_READ_ONLY_VIEWER)


def _has_grant(user, field: str) -> bool:
    if not user_has_any_role(user, WORKFLOW_FINANCIAL_ROLES):
        return False
    return WorkflowAuthorization.objects.filter(
        user_id=user.pk,
        **{field: True},
    ).exists()


def can_approve_vendor_bills(user) -> bool:
    return _has_grant(user, "can_approve_vendor_bills")


def can_pay_vendor_bills(user) -> bool:
    return _has_grant(user, "can_pay_vendor_bills")


def require_bill_editor(user) -> None:
    if not user_has_any_role(user, BILL_EDITOR_ROLES):
        raise PermissionDenied("Only administrators and bookkeepers can create or submit vendor bills.")


def require_bill_approver(user) -> None:
    if not can_approve_vendor_bills(user):
        raise PermissionDenied("You are not authorized to approve vendor bills.")


def require_vendor_payer(user) -> None:
    if not can_pay_vendor_bills(user):
        raise PermissionDenied("You are not authorized to record vendor bill payments.")


def require_grant_administrator(user) -> None:
    if not user_has_any_role(user, (ROLE_ADMIN,)):
        raise PermissionDenied("Only PropertyLedger administrators can change workflow authorizations.")


def require_maintenance_editor(user) -> None:
    if not user_has_any_role(user, MAINTENANCE_EDITOR_ROLES):
        raise PermissionDenied("You are not authorized to change maintenance requests.")

