from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from ledgeros.models import LedgerOSConnectionSettings, Owner, Property, PropertyLedgerAccountMapping, PropertyLedgerSetup, RoleLandingPage, Tenant
from ledgeros.navigation import get_home_redirect_url
from ledgeros.roles import (
    ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_GROUP_NAMES, ROLE_OWNER_VIEWER,
    ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER, assign_user_role, user_has_any_role,
)
from ledgeros.services import HealthCheckResult
from payments.models import TenantPayment


class WorkflowHomeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="workflow-user")
        self.client.force_login(self.user)
        self.health = patch("ledgeros.services.LedgerOSHealthCheckService.check")
        self.probe = self.health.start()
        self.addCleanup(self.health.stop)
        self.probe.return_value = HealthCheckResult(healthy=True, source="ledgeros", details={})

    def login_role(self, role):
        assign_user_role(self.user, role)

    def test_all_roles_share_home_and_preserve_setup_route(self):
        for role in ROLE_GROUP_NAMES:
            with self.subTest(role=role):
                self.login_role(role)
                response = self.client.get(reverse("app-home"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "What would you like to do today?")
                for title in ("Collect Rent / Deposit", "Get Billed &amp; Pay Vendors", "Log Maintenance Request"):
                    self.assertContains(response, title)
                self.assertEqual(get_home_redirect_url(self.user), reverse("app-home"))
        self.assertEqual(resolve("/").url_name, "ledgeros-setup")

    def test_anonymous_login_and_home_post_have_no_workflow_side_effect(self):
        self.assertEqual(self.client.post(reverse("app-home"), {"action": "sync"}).status_code, 405)
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("app-home")), "/login/?next=/home/", fetch_redirect_response=False)
        self.assertEqual(get_home_redirect_url(AnonymousUser()), reverse("login"))

    def test_fresh_home_get_has_no_database_writes_or_mutation_requests(self):
        self.login_role(ROLE_ADMIN)
        self.assertFalse(PropertyLedgerSetup.objects.exists())
        self.assertFalse(LedgerOSConnectionSettings.objects.exists())
        with patch("payments.services.urlopen") as posting_transport, CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("app-home"))
        self.assertEqual(response.status_code, 200)
        writes = [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]
        self.assertEqual(writes, [])
        posting_transport.assert_not_called()
        self.probe.assert_called_once()
        self.assertFalse(PropertyLedgerSetup.objects.exists())
        self.assertFalse(LedgerOSConnectionSettings.objects.exists())
        self.assertContains(response, "Setup incomplete")

    def test_unassigned_users_have_guidance_without_sensitive_queues(self):
        owner = Owner.objects.create(name="Private owner")
        property_obj = Property.objects.create(name="Private property", primary_owner=owner)
        tenant = Tenant.objects.create(name="Private tenant")
        TenantPayment.objects.create(property=property_obj, tenant=tenant, payment_date=date(2026, 10, 21), amount="100.00", payment_method="cash", reference="PRIVATE-RECEIPT")
        response = self.client.get(reverse("app-home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ask an administrator to assign your role")
        self.assertNotContains(response, "PRIVATE-RECEIPT")
        self.assertEqual(response.context["work_queues"], [])
        self.assertFalse(user_has_any_role(self.user, (ROLE_ADMIN,)))
        self.assertEqual(self.client.get(reverse("vendor-bill-create")).status_code, 403)

    def test_navigation_matches_destination_roles_and_admin_staff_access(self):
        for role in ROLE_GROUP_NAMES:
            self.login_role(role)
            response = self.client.get(reverse("app-home"))
            for group in response.context["navigation_groups"]:
                for item in group["items"]:
                    match = resolve(item["url"])
                    allowed = getattr(getattr(match.func, "view_class", None), "allowed_roles", ())
                    if allowed:
                        self.assertTrue(user_has_any_role(self.user, allowed), (role, item))
            self.assertNotContains(response, 'href="/admin/"')  # role alone does not confer Django staff access
            if role != ROLE_ADMIN:
                self.assertNotContains(response, 'href="/">Setup</a>')

    def test_viewers_get_read_links_without_creation_actions(self):
        for role in (ROLE_PROPERTY_MANAGER, ROLE_OWNER_VIEWER, ROLE_READ_ONLY_VIEWER):
            self.login_role(role)
            response = self.client.get(reverse("app-home"))
            for route in ("charge-create", "tenant-payment-create", "vendor-bill-create"):
                self.assertNotContains(response, f'href="{reverse(route)}"')
            self.assertContains(response, f'href="{reverse("invoice-list")}"')
            self.assertContains(response, f'href="{reverse("vendor-bill-list")}"')

    def test_real_receipt_queue_excludes_finalized_and_voided_and_is_bounded(self):
        self.login_role(ROLE_BOOKKEEPER)
        owner = Owner.objects.create(name="Owner")
        property_obj = Property.objects.create(name="Building", primary_owner=owner)
        tenant = Tenant.objects.create(name="Avery")
        for i in range(8):
            TenantPayment.objects.create(property=property_obj, tenant=tenant, payment_date=date(2026, 10, 21), amount="100.00", payment_method="cash", reference=f"Receipt {i}", status="draft")
        for status in ("posted", "voided"):
            TenantPayment.objects.create(property=property_obj, tenant=tenant, payment_date=date(2026, 10, 21), amount="100.00", payment_method="cash", reference=f"Excluded {status}", status=status)
        response = self.client.get(reverse("app-home"))
        queue = next(q for q in response.context["work_queues"] if q["key"] == "receipts")
        self.assertEqual(queue["count"], 8)
        self.assertEqual(len(queue["items"]), 5)
        self.assertNotContains(response, "Excluded")
        self.assertContains(response, "Showing 5 of 8")

    def test_outage_and_missing_configuration_are_distinct_and_do_not_invent_balances(self):
        self.login_role(ROLE_BOOKKEEPER)
        for details, text in (({"error": "missing_configuration"}, "LedgerOS configuration needed"), ({"error": "connection failed"}, "LedgerOS unavailable"), ({"http_status": 403}, "LedgerOS access denied")):
            self.probe.return_value = HealthCheckResult(healthy=False, source="ledgeros", details=details)
            response = self.client.get(reverse("app-home"))
            self.assertContains(response, text)
            self.assertContains(response, "Unavailable")
            self.assertNotContains(response, "$0")
            self.assertNotContains(response, f'href="{reverse("vendor-bill-create")}"')
            self.assertContains(response, "Combined rent and deposit receipts are not available yet")
            self.assertContains(response, "Maintenance requests are not available yet")

    def test_read_only_post_attempts_are_denied_before_accounting_services(self):
        for role in (ROLE_PROPERTY_MANAGER, ROLE_OWNER_VIEWER, ROLE_READ_ONLY_VIEWER):
            self.login_role(role)
            for route, args in (("vendor-bill-detail", [1]), ("tenant-payment-detail", [1]), ("tenant-payment-list", []), ("security-deposit-list", []), ("security-deposit-detail", [1]), ("invoice-detail", [1])):
                with self.subTest(role=role, route=route), patch("payments.services.LedgerOSSyncEventService._submit") as submit:
                    self.assertEqual(self.client.post(reverse(route, args=args), {"action": "sync"}).status_code, 403)
                    submit.assert_not_called()

    def test_inactive_users_have_no_role_access_even_with_group_or_superuser(self):
        self.login_role(ROLE_ADMIN)
        self.user.is_active = False
        self.user.is_superuser = True
        self.assertFalse(user_has_any_role(self.user, (ROLE_ADMIN,)))

    def test_health_probe_can_read_unsaved_configuration_without_bootstrap(self):
        self.health.stop()
        with patch.dict("os.environ", {"LEDGEROS_HMAC_SECRET": ""}), CaptureQueriesContext(connection) as queries:
            from ledgeros.services import LedgerOSHealthCheckService
            result = LedgerOSHealthCheckService.check(connection_settings=LedgerOSConnectionSettings())
        self.assertFalse(result.healthy)
        self.assertEqual(len(queries), 0)

    def test_ready_home_exposes_existing_creation_links_without_posting(self):
        self.login_role(ROLE_BOOKKEEPER)
        setup = PropertyLedgerSetup.objects.create(setup_status="complete", ledgeros_entity_id="entity", ledgeros_entity_name="Books", ledgeros_accounting_period_id="period", ledgeros_accounting_period_name="Open period", last_ledgeros_health_check_healthy=True, last_setup_smoke_healthy=True)
        for key in setup.REQUIRED_ACCOUNT_MAPPING_KEYS:
            PropertyLedgerAccountMapping.objects.create(setup=setup, mapping_key=key, ledgeros_account_id=key, ledgeros_account_name=key, ledgeros_account_type=sorted(PropertyLedgerAccountMapping.ACCOUNT_TYPE_HINTS[key])[0])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("app-home"))
        self.assertTrue(response.context["home_setup_complete"])
        for route in ("charge-create", "tenant-payment-create", "vendor-bill-create"):
            self.assertContains(response, f'href="{reverse(route)}"')
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_read_only_receipt_detail_hides_writes_but_keeps_allocation_history(self):
        self.login_role(ROLE_READ_ONLY_VIEWER)
        owner = Owner.objects.create(name="Owner")
        property_obj = Property.objects.create(name="Building", primary_owner=owner)
        tenant = Tenant.objects.create(name="Avery")
        receipt = TenantPayment.objects.create(property=property_obj, tenant=tenant, payment_date=date(2026, 10, 21), amount="100.00", payment_method="cash")
        response = self.client.get(reverse("tenant-payment-detail", args=[receipt.pk]))
        self.assertContains(response, "Allocations")
        self.assertNotContains(response, "Auto allocate remaining")
        self.assertNotContains(response, "Retry and finalize payment")
        self.assertNotContains(response, reverse("tenant-payment-edit", args=[receipt.pk]))

    def test_post_migrate_does_not_create_or_rewrite_legacy_landing_config(self):
        from types import SimpleNamespace
        from ledgeros.signals import bootstrap_role_groups
        original = RoleLandingPage.objects.create(group_name="Historical", landing_url_name="reports-home", priority=7, is_active=False)
        bootstrap_role_groups(sender=SimpleNamespace(name="ledgeros"))
        original.refresh_from_db()
        self.assertEqual(RoleLandingPage.objects.count(), 1)
        self.assertEqual(original.priority, 7)
        self.assertFalse(original.is_active)
