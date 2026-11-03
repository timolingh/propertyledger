from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import Owner, Property
from ledgeros.roles import ROLE_BOOKKEEPER, assign_user_role
from payments.maintenance_services import MaintenanceRequestService
from payments.models import MaintenanceCategory, MaintenanceRequest, Vendor, VendorBill


class BillSubmissionNavigationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("bill-entry")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        self.vendor = Vendor.objects.create(name="Plumber")
        self.property = Property.objects.create(name="Building", primary_owner=Owner.objects.create(name="Owner"))
        self.create_url = reverse("vendor-bill-create")
        self.source = reverse("vendor-bill-list") + "?payment_status=not_posted"
        self.data = {
            "vendor": self.vendor.pk, "property": self.property.pk,
            "bill_date": "2026-11-02", "amount": "125.00",
            "expense_category": "repairs_and_maintenance", "action": "submit",
        }
        transport = patch("payments.services.LedgerOSSyncEventService._submit")
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    def test_submission_returns_to_original_page_with_dismissible_confirmation(self):
        response = self.client.get(self.create_url, HTTP_REFERER="http://testserver" + self.source)
        return_url = response.context["bill_return_url"]
        response = self.client.post(self.create_url, {**self.data, "return_url": return_url}, follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("vendor-bill-list"))
        self.assertEqual(response.request["QUERY_STRING"], "payment_status=not_posted")
        self.assertContains(response, "Vendor bill created and submitted for independent approval.")
        self.assertContains(response, 'aria-label="Dismiss message"')
        bill = VendorBill.objects.get()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.SUBMITTED)
        self.assertIsNone(bill.sync_record_id)
        self.transport.assert_not_called()

    def test_validation_error_preserves_return_page_for_correction(self):
        response = self.client.post(self.create_url, {**self.data, "amount": "", "return_url": self.source})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{self.source}"')
        self.assertFalse(VendorBill.objects.exists())
        response = self.client.post(self.create_url, {**self.data, "return_url": response.context["bill_return_url"]})
        self.assertEqual(response.url, self.source)

    def test_missing_unsafe_or_self_referring_destinations_use_bill_list(self):
        for target in ("", "https://outside.example/", "//outside.example/", "javascript:alert(1)",
                       "http://testserver//outside.example/", "http://testserver/\\outside.example/", self.create_url):
            with self.subTest(target=target):
                response = self.client.post(self.create_url, {**self.data, "return_url": target})
                self.assertEqual(response.url, reverse("vendor-bill-list"))

    def test_save_draft_still_opens_bill_detail(self):
        response = self.client.post(self.create_url, {**self.data, "action": "draft", "return_url": self.source})
        bill = VendorBill.objects.get()
        self.assertEqual(response.url, reverse("vendor-bill-detail", args=[bill.pk]))

    def test_maintenance_submission_returns_to_request_and_replay_reuses_bill(self):
        request = MaintenanceRequestService.create(
            actor=self.user, property=self.property, description="Fix leak",
            category=MaintenanceCategory.objects.create(name="Plumbing"),
            priority=MaintenanceRequest.Priority.NORMAL,
        )
        url = reverse("maintenance-bill-create", args=[request.pk])
        source = reverse("maintenance-request-detail", args=[request.pk])
        response = self.client.get(url, HTTP_REFERER="http://testserver" + source)
        data = {**self.data, "handoff_token": response.context["handoff_token"],
                "return_url": response.context["bill_return_url"]}
        for _ in range(2):
            response = self.client.post(url, data)
            self.assertEqual(response.url, source)
        bill = VendorBill.objects.get()
        self.assertEqual(bill.maintenance_request_id, request.pk)
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.SUBMITTED)
        self.assertEqual(bill.submission_version, 1)
        self.transport.assert_not_called()
