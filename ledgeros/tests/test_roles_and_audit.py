from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import AuditLog
from ledgeros.models import RoleLandingPage
from ledgeros.navigation import ensure_role_landing_pages
from ledgeros.roles import (
    ROLE_ADMIN,
    ROLE_BOOKKEEPER,
    ROLE_OWNER_VIEWER,
    ROLE_PROPERTY_MANAGER,
    ROLE_READ_ONLY_VIEWER,
    assign_user_role,
    ensure_role_groups,
    get_user_role_label,
)


class RoleBootstrapTests(TestCase):
    def test_ensure_role_groups_creates_expected_groups(self):
        groups = ensure_role_groups()

        self.assertCountEqual(
            groups.keys(),
            {
                ROLE_ADMIN,
                ROLE_PROPERTY_MANAGER,
                ROLE_BOOKKEEPER,
                ROLE_OWNER_VIEWER,
                ROLE_READ_ONLY_VIEWER,
            },
        )

    def test_ensure_role_groups_assigns_default_permissions(self):
        groups = ensure_role_groups()

        property_manager_perms = set(
            groups[ROLE_PROPERTY_MANAGER].permissions.values_list("codename", flat=True)
        )
        self.assertIn("add_property", property_manager_perms)
        self.assertIn("change_lease", property_manager_perms)
        self.assertIn("view_tenantcharge", property_manager_perms)
        self.assertNotIn("delete_property", property_manager_perms)

        bookkeeper_perms = set(
            groups[ROLE_BOOKKEEPER].permissions.values_list("codename", flat=True)
        )
        self.assertIn("add_vendorbill", bookkeeper_perms)
        self.assertIn("change_tenantpayment", bookkeeper_perms)
        self.assertIn("view_ownercontributiondistribution", bookkeeper_perms)
        self.assertNotIn("delete_vendorbill", bookkeeper_perms)

        read_only_perms = set(
            groups[ROLE_READ_ONLY_VIEWER].permissions.values_list("codename", flat=True)
        )
        self.assertIn("view_property", read_only_perms)
        self.assertIn("view_auditlog", read_only_perms)
        self.assertNotIn("add_property", read_only_perms)


class RoleAssignmentTests(TestCase):
    def test_assign_user_role_updates_groups_and_label(self):
        user = get_user_model().objects.create_user(username="tester", password="password")

        assign_user_role(user, ROLE_BOOKKEEPER)
        user.refresh_from_db()

        self.assertEqual(get_user_role_label(user), "Bookkeeper")
        self.assertTrue(user.groups.filter(name="PropertyLedger Bookkeeper").exists())
        self.assertFalse(user.groups.filter(name="PropertyLedger Admin").exists())


class AuditLoggingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="password")

    def test_failed_login_is_audited(self):
        self.assertFalse(self.client.login(username="tester", password="wrong-password"))

        entry = AuditLog.objects.get(action="login_failed")
        self.assertEqual(entry.outcome, AuditLog.Outcome.FAILURE)
        self.assertEqual(entry.record_type, "User")
        self.assertEqual(entry.record_id, "tester")
        self.assertEqual(entry.source, "django_auth")

    def test_access_denied_is_audited_for_role_restricted_view(self):
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        self.client.force_login(self.user)

        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Access denied", status_code=403)
        self.assertContains(response, "Go back", status_code=403)
        entry = AuditLog.objects.get(action="access_denied")
        self.assertEqual(entry.outcome, AuditLog.Outcome.FAILURE)
        self.assertEqual(entry.record_type, "LedgerOSSetupView")
        self.assertEqual(entry.record_id, reverse("ledgeros-setup"))
        self.assertEqual(entry.actor, self.user)

    def test_audit_log_view_is_visible_to_reporting_roles(self):
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        self.client.force_login(self.user)
        AuditLog.objects.create(
            action="seeded_action",
            actor=self.user,
            record_type="TenantCharge",
            record_id="123",
            source="ui",
            outcome=AuditLog.Outcome.SUCCESS,
        )

        response = self.client.get(reverse("audit-log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "seeded_action")


class AppLoginTests(TestCase):
    def setUp(self):
        ensure_role_landing_pages()

    def test_non_staff_user_can_sign_in_and_use_app_login(self):
        user = get_user_model().objects.create_user(username="viewer", password="password")
        assign_user_role(user, ROLE_READ_ONLY_VIEWER)

        response = self.client.post(
            reverse("login"),
            {"username": "viewer", "password": "password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/home/")

        home = self.client.get(reverse("app-home"))
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home.url, reverse("reports-home"))

    def test_custom_group_redirects_via_config_table(self):
        custom_group = Group.objects.create(name="PropertyLedger Inspector")
        RoleLandingPage.objects.create(
            group_name=custom_group.name,
            landing_url_name="reports-home",
            priority=5,
        )
        user = get_user_model().objects.create_user(username="inspector", password="password")
        user.groups.add(custom_group)

        self.client.login(username="inspector", password="password")
        response = self.client.get(reverse("app-home"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("reports-home"))
