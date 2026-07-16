from __future__ import annotations

from django.urls import reverse

from ledgeros.models import RoleLandingPage
from ledgeros.roles import ROLE_ADMIN, ROLE_GROUP_NAMES, ROLE_BOOKKEEPER, ROLE_OWNER_VIEWER, ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER

DEFAULT_ROLE_LANDING_PAGES = {
    ROLE_GROUP_NAMES[ROLE_ADMIN]: ("ledgeros-setup", 0),
    ROLE_GROUP_NAMES[ROLE_PROPERTY_MANAGER]: ("reports-home", 10),
    ROLE_GROUP_NAMES[ROLE_BOOKKEEPER]: ("payments-home", 20),
    ROLE_GROUP_NAMES[ROLE_OWNER_VIEWER]: ("reports-home", 30),
    ROLE_GROUP_NAMES[ROLE_READ_ONLY_VIEWER]: ("reports-home", 40),
}


def ensure_role_landing_pages() -> dict[str, RoleLandingPage]:
    configs: dict[str, RoleLandingPage] = {}
    for group_name, (landing_url_name, priority) in DEFAULT_ROLE_LANDING_PAGES.items():
        config, _ = RoleLandingPage.objects.update_or_create(
            group_name=group_name,
            defaults={
                "landing_url_name": landing_url_name,
                "priority": priority,
                "is_active": True,
            },
        )
        configs[group_name] = config
    return configs


def get_home_redirect_url(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return reverse("login")
    if user.is_superuser or user.groups.filter(name=ROLE_GROUP_NAMES[ROLE_ADMIN]).exists():
        return reverse("ledgeros-setup")

    group_names = list(user.groups.values_list("name", flat=True))
    config = (
        RoleLandingPage.objects.filter(
            is_active=True,
            group_name__in=group_names,
        )
        .order_by("priority", "group_name", "id")
        .first()
    )
    if config is not None:
        return reverse(config.landing_url_name)
    return reverse("reports-home")
