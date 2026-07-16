from __future__ import annotations

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from ledgeros.audit import audit_failure
from ledgeros.navigation import ensure_role_landing_pages
from ledgeros.roles import ensure_role_groups

ROLE_PERMISSION_BOOTSTRAP_APPS = {"ledgeros", "payments", "reports"}


@receiver(post_migrate, dispatch_uid="ledgeros.ensure_role_groups")
def bootstrap_role_groups(sender, **kwargs) -> None:
    if getattr(sender, "name", "") not in ROLE_PERMISSION_BOOTSTRAP_APPS:
        return
    ensure_role_groups()
    ensure_role_landing_pages()


@receiver(user_login_failed, dispatch_uid="ledgeros.audit_login_failed")
def audit_login_failed(sender, credentials, request, **kwargs) -> None:
    username = ""
    if isinstance(credentials, dict):
        username = str(credentials.get("username") or credentials.get("email") or credentials.get("login") or "").strip()

    audit_failure(
        action="login_failed",
        record_type="User",
        record_id=username or "unknown",
        source="django_auth",
        metadata={
            "path": getattr(request, "path", "") if request is not None else "",
            "username": username or "unknown",
        },
    )
