from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import AuditLog
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
    def test_non_staff_user_can_sign_in_and_use_app_login(self):
        user = get_user_model().objects.create_user(username="viewer", password="password")
        assign_user_role(user, ROLE_READ_ONLY_VIEWER)

        response = self.client.post(
            reverse("login"),
            {"username": "viewer", "password": "password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")

        home = self.client.get(reverse("reports-home"))
        self.assertEqual(home.status_code, 200)
