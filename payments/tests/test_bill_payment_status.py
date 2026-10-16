import json
import os
from io import StringIO
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.models import Vendor, VendorBill, VendorPayment
from payments.services import VendorPaymentService
from payments.tests.test_payments_workflow import _FakeResponse, _configure_ledgeros_settings, _configure_epic5_mappings


class BillPaymentStatusTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        self.property = Property.objects.create(name="Building", primary_owner=Owner.objects.create(name="Owner"))
        self.vendor = Vendor.objects.create(name="Vendor")
        self.user = get_user_model().objects.create_user("bookkeeper")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)

    def synced_record(self, kind, pk, response=None, resource_type=None):
        return LedgerOSSyncRecord.objects.create(
            local_object_type=kind, local_object_id=str(pk), source_event_type=kind,
            external_id=f"{kind}:{pk}", idempotency_key=f"{kind}:{pk}", request_hash="test",
            ledgeros_resource_type=resource_type or kind, ledgeros_resource_id=str(pk),
            status=LedgerOSSyncRecord.Status.SUCCEEDED, response_payload=response,
        )

    def bill(self, name, posted=True):
        bill = VendorBill.objects.create(vendor=self.vendor, property=self.property,
            bill_date=date(2026, 5, 1), amount="100.00", notes=name,
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            status=VendorBill.Status.POSTED if posted else VendorBill.Status.DRAFT)
        if posted:
            bill.sync_record = self.synced_record("vendor-bill", bill.pk)
            bill.save()
        return bill

    def result(self, bill, status, paid="0.00", credited="0.00", balance="100.00"):
        return {"id": bill.pk, "external_bill_number": f"vendor-bill:{bill.pk}",
                "status": "posted", "payment_status": status, "total_amount": "100.00",
                "amount_paid": paid, "amount_credited": credited, "outstanding_balance": balance}

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_list_and_detail_use_batched_upstream_balances_and_filter(self, transport):
        unpaid = self.bill("unpaid")
        partial = self.bill("partial")
        paid = self.bill("paid")
        self.bill("draft", posted=False)
        rows = [self.result(unpaid, "unpaid"), self.result(partial, "partially_paid", "40.00", "10.00", "50.00"),
                self.result(paid, "paid", "100.00", balance="0.00")]
        transport.return_value = _FakeResponse(status=200, payload=json.dumps({"results": rows}).encode())
        response = self.client.get(reverse("vendor-bill-list"), {"payment_status": "partially_paid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["object"].pk for row in response.context["rows"]], [partial.pk])
        self.assertContains(response, "Partially paid")
        self.assertContains(response, 'value="partially_paid" selected')
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(transport.call_args.args[0].method, "GET")
        self.assertIn("external_bill_number=vendor-bill%3A", transport.call_args.args[0].full_url)
        transport.return_value = _FakeResponse(status=200, payload=json.dumps({"results": [rows[1]]}).encode())
        response = self.client.get(reverse("vendor-bill-detail", args=[partial.pk]))
        self.assertContains(response, "Partially paid")
        self.assertContains(response, "50.00")
        self.assertContains(response, "10.00")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_legacy_reconciliation_command_previews_and_links_without_reposting(self, transport):
        _configure_epic5_mappings()
        bill = self.bill("legacy")
        payment = VendorPayment.objects.create(
            vendor=self.vendor, vendor_bill=bill, payment_date=date(2026, 5, 2), amount=Decimal("100.00"),
            payment_method=VendorPayment.PaymentMethod.CREDIT_CARD, credit_card_account_name="Card",
            status=VendorPayment.Status.POSTED,
        )
        legacy = self.synced_record("legacy-command", payment.pk,
            {"sync_event": {"id": 12}, "journal_entry": {"id": 77}}, "sync_event")
        payment.sync_record = legacy
        payment.save()
        output = StringIO()
        call_command("reconcile_bill_card_payments", payment_id=payment.pk, stdout=output)
        self.assertIn("Previewed 1", output.getvalue())
        transport.assert_not_called()
        transport.return_value = _FakeResponse(status=201, payload=json.dumps({
            "payment": {"id": 55}, "journal_entry": {"id": 77, "status": "posted"}}).encode())
        call_command("reconcile_bill_card_payments", payment_id=payment.pk, apply=True, stdout=StringIO())
        self.assertEqual(json.loads(transport.call_args.args[0].data)["existing_sync_event_id"], 12)
        output = StringIO()
        call_command("reconcile_bill_card_payments", payment_id=payment.pk, apply=True, stdout=output)
        self.assertIn("Processed 0", output.getvalue())
        self.assertEqual(transport.call_count, 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.response_payload["journal_entry"]["id"], 77)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_malformed_upstream_amounts_cannot_appear_paid(self, transport):
        bill = self.bill("bad response")
        row = self.result(bill, "paid", paid="NaN", balance="0.00")
        transport.return_value = _FakeResponse(status=200, payload=json.dumps({"results": [row]}).encode())
        response = self.client.get(reverse("vendor-bill-list"), {"payment_status": "unavailable"})
        self.assertEqual([row["object"].pk for row in response.context["rows"]], [bill.pk])
        self.assertContains(response, "Unavailable")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_unavailable_is_not_unpaid_and_drafts_do_not_trigger_reads(self, transport):
        posted = self.bill("posted")
        draft = self.bill("draft", posted=False)
        transport.side_effect = URLError("offline")
        response = self.client.get(reverse("vendor-bill-list"), {"payment_status": "unavailable"})
        self.assertEqual([row["object"].pk for row in response.context["rows"]], [posted.pk])
        self.assertContains(response, "Unavailable")
        transport.reset_mock()
        response = self.client.get(reverse("vendor-bill-list"), {"payment_status": "paid"})
        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "could not be read from LedgerOS")
        transport.reset_mock()
        response = self.client.get(reverse("vendor-bill-detail", args=[draft.pk]))
        self.assertContains(response, "Not posted")
        transport.assert_not_called()

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_legacy_card_payment_is_flagged_until_explicitly_linked(self, transport):
        bill = self.bill("old card")
        payment = VendorPayment.objects.create(vendor=self.vendor, vendor_bill=bill, payment_date=date(2026, 5, 2),
            amount="100.00", payment_method=VendorPayment.PaymentMethod.CREDIT_CARD,
            credit_card_account_name="Card", status=VendorPayment.Status.POSTED)
        payment.sync_record = self.synced_record("old-card", payment.pk, resource_type="sync_event")
        payment.save()
        transport.return_value = _FakeResponse(status=200, payload=json.dumps({"results": [self.result(bill, "unpaid")]}).encode())
        response = self.client.get(reverse("vendor-bill-list"))
        self.assertContains(response, "Needs review")
        self.assertContains(response, "card payment")
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(transport.call_args.args[0].method, "GET")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_read_only_viewer_can_filter_without_posting(self, transport):
        self.bill("draft", posted=False)
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        response = self.client.get(reverse("vendor-bill-list"), {"payment_status": "not_posted"})
        self.assertEqual(response.status_code, 200)
        transport.assert_not_called()

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_card_payment_uses_bill_settlement_endpoint_and_legacy_link(self, transport):
        _configure_epic5_mappings()
        bill = self.bill("card")
        transport.return_value = _FakeResponse(status=201, payload=json.dumps({
            "payment": {"id": 55}, "journal_entry": {"id": 77, "status": "posted"}}).encode())
        payment = VendorPayment.objects.create(vendor=self.vendor, vendor_bill=bill, payment_date=date(2026, 5, 2),
            amount="100.00", payment_method=VendorPayment.PaymentMethod.CREDIT_CARD, credit_card_account_name="Card")
        legacy = self.synced_record("legacy-card", payment.pk, {"sync_event": {"id": 12}, "journal_entry": {"id": 77}}, "sync_event")
        payment.sync_record = legacy
        payment.save()
        payment.refresh_from_db()
        VendorPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        request = transport.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/v1/payments/"))
        payload = json.loads(request.data)
        self.assertEqual(payload["funding_account_code"], "2100")
        self.assertEqual(payload["existing_sync_event_id"], 12)
        self.assertEqual(payment.sync_record.ledgeros_resource_type, "payment")
        self.assertNotEqual(payment.sync_record_id, legacy.pk)
        VendorPaymentService.sync_payment(payment)
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_failed_legacy_link_retries_the_same_event_without_reposting(self, transport):
        _configure_epic5_mappings()
        bill = self.bill("legacy retry")
        payment = VendorPayment.objects.create(
            vendor=self.vendor, vendor_bill=bill, payment_date=date(2026, 5, 2), amount=Decimal("100.00"),
            payment_method=VendorPayment.PaymentMethod.CREDIT_CARD, credit_card_account_name="Card",
            status=VendorPayment.Status.POSTED,
        )
        legacy = self.synced_record("vendor_payment", payment.pk,
            {"sync_event": {"id": 12}, "journal_entry": {"id": 77}}, "sync_event")
        legacy.source_event_type = "vendor_payment.credit_card"
        legacy.save()
        payment.sync_record = legacy
        payment.save()
        transport.side_effect = [URLError("timeout"), _FakeResponse(status=200, payload=json.dumps({
            "payment": {"id": 55}, "journal_entry": {"id": 77, "status": "posted"}}).encode())]
        VendorPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
        VendorPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        first, second = [call.args[0] for call in transport.call_args_list]
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.get_header("Idempotency-key"), second.get_header("Idempotency-key"))
        self.assertEqual(json.loads(second.data)["existing_sync_event_id"], 12)
