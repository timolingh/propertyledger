from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import Group


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
