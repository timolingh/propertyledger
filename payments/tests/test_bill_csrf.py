from datetime import date
from html.parser import HTMLParser
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from ledgeros.models import Owner, Property
from ledgeros.roles import ROLE_ADMIN, assign_user_role
from payments.models import Vendor, VendorBill


class _CSRFTokenParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrfmiddlewaretoken":
            self.token = attrs["value"]


class BillCSRFTests(TestCase):
    def setUp(self):
        readiness = patch("payments.views.LedgerOSWriteReadinessService.require")
        readiness.start()
        self.addCleanup(readiness.stop)
        user = get_user_model().objects.create_user(username="bill-csrf")
        assign_user_role(user, ROLE_ADMIN)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(user)
        owner = Owner.objects.create(name="Owner")
        property_obj = Property.objects.create(name="Property", primary_owner=owner)
        bill = VendorBill.objects.create(
            vendor=Vendor.objects.create(name="Vendor"),
            property=property_obj,
            bill_date=date(2026, 2, 1),
            amount="125.00",
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
        )
        self.url = reverse("vendor-bill-detail", args=[bill.pk])

    @patch("payments.views.VendorBillService.sync_bill")
    def test_bill_form_survives_other_localhost_app_cookie_changes(self, sync_bill):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        parser = _CSRFTokenParser()
        parser.feed(response.content.decode())
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)

        # Cookies are shared across ports. Simulate a login to another Django app.
        self.client.cookies["csrftoken"] = "a" * 32
        self.client.cookies["sessionid"] = "another-app-session"
        response = self.client.post(
            self.url, {"action": "sync", "csrfmiddlewaretoken": parser.token}
        )

        self.assertRedirects(response, self.url)
        sync_bill.assert_called_once()

    @patch("payments.views.VendorBillService.sync_bill")
    def test_bill_sync_rejects_missing_or_incorrect_csrf_token(self, sync_bill):
        self.client.get(self.url)
        for token in (None, "a" * 64):
            with self.subTest(token=token):
                data = {"action": "sync"}
                if token is not None:
                    data["csrfmiddlewaretoken"] = token
                self.assertEqual(self.client.post(self.url, data).status_code, 403)
        sync_bill.assert_not_called()
