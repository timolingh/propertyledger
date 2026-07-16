from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin

from ledgeros.audit import audit_failure
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_OWNER_VIEWER, ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER, get_user_role_label, user_has_any_role


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles: tuple[str, ...] = ()
    login_url = settings.LOGIN_URL

    def has_role_access(self, user) -> bool:
        if not self.allowed_roles:
            return True
        return user_has_any_role(user, self.allowed_roles)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.has_role_access(request.user):
            audit_failure(
                action="access_denied",
                record_type=self.__class__.__name__,
                record_id=request.path,
                user=request.user,
                source="ui",
                metadata={
                    "allowed_roles": list(self.allowed_roles),
                    "current_role": get_user_role_label(request.user),
                    "method": request.method,
                },
            )
            raise PermissionDenied("You do not have access to this workflow.")
        return super().dispatch(request, *args, **kwargs)


class AdminRoleRequiredMixin(RoleRequiredMixin):
    allowed_roles = (ROLE_ADMIN,)


class PropertyManagementRoleRequiredMixin(RoleRequiredMixin):
    allowed_roles = (ROLE_ADMIN, ROLE_PROPERTY_MANAGER)


class BookkeepingRoleRequiredMixin(RoleRequiredMixin):
    allowed_roles = (ROLE_ADMIN, ROLE_BOOKKEEPER)


class ReportingRoleRequiredMixin(RoleRequiredMixin):
    allowed_roles = (
        ROLE_ADMIN,
        ROLE_PROPERTY_MANAGER,
        ROLE_BOOKKEEPER,
        ROLE_OWNER_VIEWER,
        ROLE_READ_ONLY_VIEWER,
    )


class OwnerViewerRoleRequiredMixin(ReportingRoleRequiredMixin):
    allowed_roles = (
        ROLE_ADMIN,
        ROLE_PROPERTY_MANAGER,
        ROLE_BOOKKEEPER,
        ROLE_OWNER_VIEWER,
    )
