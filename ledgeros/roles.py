from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist


ROLE_ADMIN = "admin"
ROLE_PROPERTY_MANAGER = "property_manager"
ROLE_BOOKKEEPER = "bookkeeper"
ROLE_OWNER_VIEWER = "owner_viewer"
ROLE_READ_ONLY_VIEWER = "read_only_viewer"

ROLE_LABELS = {
    ROLE_ADMIN: "Admin",
    ROLE_PROPERTY_MANAGER: "Property manager",
    ROLE_BOOKKEEPER: "Bookkeeper",
    ROLE_OWNER_VIEWER: "Owner viewer",
    ROLE_READ_ONLY_VIEWER: "Read-only viewer",
}

ROLE_GROUP_NAMES = {
    ROLE_ADMIN: "PropertyLedger Admin",
    ROLE_PROPERTY_MANAGER: "PropertyLedger Property Manager",
    ROLE_BOOKKEEPER: "PropertyLedger Bookkeeper",
    ROLE_OWNER_VIEWER: "PropertyLedger Owner Viewer",
    ROLE_READ_ONLY_VIEWER: "PropertyLedger Read Only Viewer",
}

ROLE_ORDER = [
    ROLE_ADMIN,
    ROLE_PROPERTY_MANAGER,
    ROLE_BOOKKEEPER,
    ROLE_OWNER_VIEWER,
    ROLE_READ_ONLY_VIEWER,
]

ROLE_PERMISSION_SPECS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    ROLE_ADMIN: {
        "ledgeros": {
            "ledgerosconnectionsettings": ("add", "change", "delete", "view"),
            "propertyledgersetup": ("add", "change", "delete", "view"),
            "propertyledgeraccountmapping": ("add", "change", "delete", "view"),
            "ledgerossyncrecord": ("add", "change", "delete", "view"),
            "auditlog": ("add", "change", "delete", "view"),
            "owner": ("add", "change", "delete", "view"),
            "property": ("add", "change", "delete", "view"),
            "unit": ("add", "change", "delete", "view"),
            "tenant": ("add", "change", "delete", "view"),
            "lease": ("add", "change", "delete", "view"),
            "tenantcharge": ("add", "change", "delete", "view"),
        },
        "payments": {
            "paymentworkflowsettings": ("add", "change", "delete", "view"),
            "tenantpayment": ("add", "change", "delete", "view"),
            "tenantpaymentapplication": ("add", "change", "delete", "view"),
            "securitydepositevent": ("add", "change", "delete", "view"),
            "vendor": ("add", "change", "delete", "view"),
            "maintenancecategory": ("add", "change", "delete", "view"),
            "vendorbill": ("add", "change", "delete", "view"),
            "vendorpayment": ("add", "change", "delete", "view"),
            "debtservicepayment": ("add", "change", "delete", "view"),
        },
        "reports": {
            "ownercontributiondistribution": ("add", "change", "delete", "view"),
        },
    },
    ROLE_PROPERTY_MANAGER: {
        "ledgeros": {
            "owner": ("add", "change", "view"),
            "property": ("add", "change", "view"),
            "unit": ("add", "change", "view"),
            "tenant": ("add", "change", "view"),
            "lease": ("add", "change", "view"),
            "tenantcharge": ("view",),
        },
        "payments": {
            "tenantpayment": ("view",),
            "securitydepositevent": ("view",),
            "vendorbill": ("view",),
            "vendorpayment": ("view",),
            "debtservicepayment": ("view",),
        },
        "reports": {
            "ownercontributiondistribution": ("view",),
        },
    },
    ROLE_BOOKKEEPER: {
        "ledgeros": {
            "owner": ("view",),
            "property": ("view",),
            "unit": ("view",),
            "tenant": ("view",),
            "lease": ("view",),
            "tenantcharge": ("view", "add", "change"),
        },
        "payments": {
            "tenantpayment": ("view", "add", "change"),
            "tenantpaymentapplication": ("view",),
            "securitydepositevent": ("view", "add", "change"),
            "vendor": ("view", "add", "change"),
            "maintenancecategory": ("view", "add", "change"),
            "vendorbill": ("view", "add", "change"),
            "vendorpayment": ("view", "add", "change"),
            "debtservicepayment": ("view", "add", "change"),
        },
        "reports": {
            "ownercontributiondistribution": ("view", "add", "change"),
        },
    },
    ROLE_OWNER_VIEWER: {
        "ledgeros": {
            "tenantcharge": ("view",),
        },
        "reports": {
            "ownercontributiondistribution": ("view",),
        },
    },
    ROLE_READ_ONLY_VIEWER: {
        "ledgeros": {
            "ledgerosconnectionsettings": ("view",),
            "propertyledgersetup": ("view",),
            "propertyledgeraccountmapping": ("view",),
            "ledgerossyncrecord": ("view",),
            "auditlog": ("view",),
            "owner": ("view",),
            "property": ("view",),
            "unit": ("view",),
            "tenant": ("view",),
            "lease": ("view",),
            "tenantcharge": ("view",),
        },
        "payments": {
            "paymentworkflowsettings": ("view",),
            "tenantpayment": ("view",),
            "tenantpaymentapplication": ("view",),
            "securitydepositevent": ("view",),
            "vendor": ("view",),
            "maintenancecategory": ("view",),
            "vendorbill": ("view",),
            "vendorpayment": ("view",),
            "debtservicepayment": ("view",),
        },
        "reports": {
            "ownercontributiondistribution": ("view",),
        },
    },
}


@dataclass(frozen=True)
class RoleAssignment:
    role: str
    group_name: str
    label: str


def ensure_role_groups() -> dict[str, Group]:
    groups: dict[str, Group] = {}
    for role, group_name in ROLE_GROUP_NAMES.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        groups[role] = group
    ensure_default_group_permissions(groups)
    return groups


def _permissions_for_model(app_label: str, model_name: str, actions: tuple[str, ...]) -> list[Permission]:
    try:
        content_type = ContentType.objects.get(app_label=app_label, model=model_name)
    except ObjectDoesNotExist:
        return []
    return list(
        Permission.objects.filter(
            content_type=content_type,
            codename__in=[f"{action}_{model_name}" for action in actions],
        )
    )


def _permissions_for_role(role: str) -> list[Permission]:
    permissions: list[Permission] = []
    for app_label, model_map in ROLE_PERMISSION_SPECS.get(role, {}).items():
        for model_name, actions in model_map.items():
            permissions.extend(_permissions_for_model(app_label, model_name, actions))
    return permissions


def ensure_default_group_permissions(groups: dict[str, Group] | None = None) -> dict[str, Group]:
    groups = groups or ensure_role_groups()
    for role, group in groups.items():
        permissions = _permissions_for_role(role)
        if permissions:
            group.permissions.add(*permissions)
    return groups


def _role_group_names() -> set[str]:
    return set(ROLE_GROUP_NAMES.values())


def get_user_role(user) -> str | None:
    if not getattr(user, "is_authenticated", False):
        return None
    group_names = set(user.groups.values_list("name", flat=True))
    for role in ROLE_ORDER:
        if ROLE_GROUP_NAMES[role] in group_names:
            return role
    return None


def get_user_role_label(user) -> str:
    role = get_user_role(user)
    if role is None:
        return "Unassigned"
    return ROLE_LABELS[role]


def user_has_any_role(user, roles: tuple[str, ...] | list[str] | set[str]) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    assigned_roles = set(user.groups.filter(name__in=_role_group_names()).values_list("name", flat=True))
    if not assigned_roles:
        return True
    allowed_group_names = {ROLE_GROUP_NAMES[role] for role in roles}
    return bool(assigned_roles & allowed_group_names)


def assign_user_role(user, role: str) -> None:
    if role not in ROLE_GROUP_NAMES:
        raise ValueError(f"Unknown role: {role}")
    groups = ensure_role_groups()
    role_group_names = _role_group_names()
    user.groups.remove(*user.groups.filter(name__in=role_group_names))
    user.groups.add(groups[role])


def current_role_assignment(user) -> RoleAssignment | None:
    role = get_user_role(user)
    if role is None:
        return None
    return RoleAssignment(role=role, group_name=ROLE_GROUP_NAMES[role], label=ROLE_LABELS[role])
