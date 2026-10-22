from __future__ import annotations

from django.urls import resolve, reverse

from ledgeros.models import RoleLandingPage
from ledgeros.roles import ROLE_ADMIN, ROLE_GROUP_NAMES, ROLE_BOOKKEEPER, ROLE_OWNER_VIEWER, ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER, get_user_role_label, user_has_any_role

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
        config, _ = RoleLandingPage.objects.get_or_create(
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
    return reverse("app-home")


def navigation_context(request):
    """Shared navigation uses each destination's own view role policy; no setup writes."""
    groups = []
    if request.user.is_authenticated:
        definitions = (
            ("Workflows", (("Home", "app-home"), ("Collect rent / deposit", "invoice-list"), ("Vendor payables", "vendor-bill-list"))),
            ("Records", (("Owners", "owner-list"), ("Properties", "property-list"), ("Units", "unit-list"), ("Tenants", "tenant-list"), ("Leases", "lease-list"), ("Vendors", "vendor-list"))),
            ("Accounting & monitoring", (("Invoices", "charge-list"), ("Payments overview", "payments-home"), ("Tenant receipts", "tenant-payment-list"), ("Security deposits", "security-deposit-list"), ("Vendor payments", "vendor-payment-list"), ("Debt service", "debt-service-payment-list"), ("Maintenance categories", "maintenance-category-list"), ("Banking", "banking-dashboard"), ("Reports", "reports-home"), ("Owner activity", "owner-activity-list"), ("Owner statements", "owner-statement"))),
            ("Administration", (("Setup", "ledgeros-setup"), ("Audit log", "audit-log"))),
        )
        for label, links in definitions:
            items = []
            for title, name in links:
                url = reverse(name)
                view = resolve(url).func.view_class
                if name != "app-home" and not user_has_any_role(request.user, getattr(view, "allowed_roles", ())):
                    continue
                items.append({"label": title, "url": url, "active": request.path == url})
            if label == "Administration" and request.user.is_active and request.user.is_staff:
                items.append({"label": "Admin", "url": reverse("admin:index"), "active": request.path.startswith("/admin/")})
            if items:
                groups.append({"label": label, "items": items})
        # Home is available even before a role has been assigned.
        if not any(item["url"] == reverse("app-home") for group in groups for item in group["items"]):
            groups.insert(0, {"label": "Workflows", "items": [{"label": "Home", "url": reverse("app-home"), "active": request.path == reverse("app-home")}]})
        candidates = [item for group in groups for item in group["items"] if request.path == item["url"] or (item["url"] != "/" and request.path.startswith(item["url"]))]
        current = max(candidates, key=lambda item: len(item["url"]), default=None)
        for group in groups:
            for item in group["items"]:
                item["active"] = item is current
    from ledgeros.permissions import BookkeepingRoleRequiredMixin
    current_view = getattr(getattr(request.resolver_match, "func", None), "view_class", None)
    create_route = getattr(current_view, "create_url_name", "")
    can_create_record = False
    if create_route:
        create_view = resolve(reverse(create_route)).func.view_class
        can_create_record = user_has_any_role(request.user, create_view.allowed_roles)
    return {"navigation_groups": groups, "navigation_role_label": get_user_role_label(request.user), "can_configure": user_has_any_role(request.user, (ROLE_ADMIN,)), "can_bookkeep": user_has_any_role(request.user, BookkeepingRoleRequiredMixin.allowed_roles), "can_create_record": can_create_record}
