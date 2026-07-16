from __future__ import annotations

from django.contrib.auth.models import Group
from ledgeros.audit import audit_failure
from ledgeros.roles import ensure_role_groups
from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate, dispatch_uid="ledgeros.ensure_role_groups")
def bootstrap_role_groups(sender, **kwargs) -> None:
    if getattr(sender, "name", "") != "ledgeros":
        return
    ensure_role_groups()


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
