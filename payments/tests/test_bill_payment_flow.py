import json
import os
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.models import Vendor, VendorBill, VendorPayment
from payments.tests.test_payments_workflow import _FakeResponse, _configure_ledgeros_settings, _configure_epic5_mappings


@patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
class BillPaymentFlowTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        _configure_epic5_mappings()
        self.user = get_user_model().objects.create_user("bill-payer")
        self.grant_admin = get_user_model().objects.create_user("grant-admin")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        assign_user_role(self.grant_admin, ROLE_ADMIN)
        WorkflowAuthorizationService.set_grants(
            target=self.user, actor=self.grant_admin,
            can_approve_vendor_bills=False, can_pay_vendor_bills=True,
        )
        self.client.force_login(self.user)
        vendor = Vendor.objects.create(name="Vendor")
        property_obj = Property.objects.create(name="Building", primary_owner=Owner.objects.create(name="Owner"))
        self.bill = VendorBill.objects.create(vendor=vendor, property=property_obj, bill_date=date(2026, 5, 1),
            amount=Decimal("100.00"), expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            status=VendorBill.Status.POSTED)
        self.bill.sync_record = LedgerOSSyncRecord.objects.create(
            local_object_type="vendor_bill", local_object_id=str(self.bill.pk), source_event_type="vendor_bill.created",
            external_id=f"vendor-bill:{self.bill.pk}", idempotency_key=f"bill:{self.bill.pk}", request_hash="bill",
            ledgeros_resource_type="bill", ledgeros_resource_id=str(self.bill.pk), status=LedgerOSSyncRecord.Status.SUCCEEDED)
        self.bill.save()
        self.bill.approval_status = VendorBill.ApprovalStatus.APPROVED
        self.bill.approved_fingerprint = VendorBillApprovalService.financial_fingerprint(self.bill)
        self.bill.save(update_fields=["approval_status", "approved_fingerprint", "updated_at"])
        self.detail_url = reverse("vendor-bill-detail", args=[self.bill.pk])
        self.pay_url = reverse("vendor-bill-pay", args=[self.bill.pk])
        self.balance = Decimal("100.00")
        self.state = "unpaid"
        self.read_patch = patch("payments.services.BillPaymentStatusService.statuses", side_effect=self.statuses)
        self.read_patch.start()
        self.addCleanup(self.read_patch.stop)

    def statuses(self, bills):
        return {bill.pk: {"status": self.state, "label": self.state, "paid": Decimal("100.00") - self.balance,
                         "credited": Decimal("0.00"), "balance": self.balance, "error": ""} for bill in bills}

    def data(self, amount="100.00"):
        response = self.client.get(self.pay_url)
        self.assertEqual(response.status_code, 200)
        return {"submission_token": response.context["form"]["submission_token"].value(),
                "payment_date": "2026-05-02", "amount": amount, "payment_method": "ach_manual",
                "bank_account_name": "Operating Bank", "credit_card_account_name": "", "memo": "Payment", "notes": ""}

    def posted(self):
        return _FakeResponse(status=201, payload=json.dumps({"payment": {"id": 22},
            "journal_entry": {"id": 33, "status": "posted"}}).encode())

    @patch("payments.services.urlopen")
    def test_bill_action_and_prefilled_form_do_not_post(self, transport):
        response = self.client.get(self.detail_url)
        self.assertContains(response, self.pay_url)
        self.assertContains(response, "Pay bill")
        response = self.client.get(self.pay_url)
        form = response.context["form"]
        self.assertEqual(form.initial["amount"], Decimal("100.00"))
        self.assertNotIn("vendor", form.fields)
        self.assertNotIn("vendor_bill", form.fields)
        self.assertNotIn("is_credit_card_payoff", form.fields)
        transport.assert_not_called()
        self.assertFalse(VendorPayment.objects.exists())

    @patch("payments.services.urlopen")
    def test_partial_payment_and_duplicate_submit_use_one_payment(self, transport):
        data = self.data("40.00")
        transport.return_value = self.posted()
        response = self.client.post(self.pay_url, data)
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        self.balance, self.state = Decimal("60.00"), "partially_paid"
        response = self.client.post(self.pay_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VendorPayment.objects.count(), 1)
        payment = VendorPayment.objects.get()
        self.assertEqual(payment.vendor_bill_id, self.bill.pk)
        self.assertEqual(payment.vendor_id, self.bill.vendor_id)
        self.assertEqual(payment.amount, Decimal("40.00"))
        self.assertEqual(payment.status, VendorPayment.Status.POSTED)
        self.assertEqual(transport.call_count, 1)
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload["source_reference"], self.bill.sync_record.external_id)
        self.assertEqual(payload["amount"], "40.00")
        self.assertContains(self.client.get(self.detail_url), "60.00")

    @patch("payments.services.urlopen")
    def test_full_payment_hides_new_payment_but_original_submission_replays(self, transport):
        data = self.data()
        transport.return_value = self.posted()
        self.client.post(self.pay_url, data)
        self.balance, self.state = Decimal("0.00"), "paid"
        self.assertNotContains(self.client.get(self.detail_url), 'href="' + self.pay_url + '"')
        self.client.post(self.pay_url, data)
        self.assertEqual(VendorPayment.objects.count(), 1)
        self.assertEqual(transport.call_count, 1)

    @patch("payments.services.urlopen")
    def test_timeout_retry_uses_same_identity_even_if_upstream_balance_is_now_zero(self, transport):
        data = self.data()
        transport.side_effect = [URLError("timeout"), self.posted()]
        self.client.post(self.pay_url, data)
        payment = VendorPayment.objects.get()
        first_key = payment.sync_record.idempotency_key
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
        self.assertContains(self.client.get(self.detail_url), "Retry payment")
        self.balance, self.state = Decimal("0.00"), "paid"
        response = self.client.post(self.pay_url, data)
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(VendorPayment.objects.count(), 1)
        self.assertEqual(payment.sync_record.idempotency_key, first_key)
        self.assertEqual(payment.status, VendorPayment.Status.POSTED)
        first, retry = [call.args[0] for call in transport.call_args_list]
        self.assertEqual(first.data, retry.data)

    @patch("payments.services.urlopen")
    def test_changed_submission_details_are_rejected(self, transport):
        data = self.data("40.00")
        transport.return_value = self.posted()
        self.client.post(self.pay_url, data)
        data["amount"] = "50.00"
        response = self.client.post(self.pay_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "different payment details")
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(VendorPayment.objects.count(), 1)

    @patch("payments.services.urlopen")
    def test_fresh_balance_validation_rejects_stale_amount(self, transport):
        data = self.data()
        self.balance = Decimal("60.00")
        response = self.client.post(self.pay_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "outstanding balance")
        transport.assert_not_called()
        self.assertFalse(VendorPayment.objects.exists())

    @patch("payments.services.urlopen")
    def test_blocked_bill_states_cannot_start_payments(self, transport):
        data = self.data()
        for state in ("not_posted", "voided", "paid", "unavailable", "needs_review"):
            with self.subTest(state=state):
                self.state = state
                response = self.client.get(self.pay_url)
                self.assertNotContains(response, '>Post payment</button>')
                response = self.client.post(self.pay_url, data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(VendorPayment.objects.exists())
        transport.assert_not_called()

    @patch("payments.services.urlopen")
    def test_read_only_user_cannot_start_or_submit_or_retry_payments(self, transport):
        data = self.data()
        transport.side_effect = URLError("timeout")
        self.client.post(self.pay_url, data)
        payment = VendorPayment.objects.get()
        transport.reset_mock()
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        self.assertEqual(self.client.get(self.pay_url).status_code, 403)
        self.assertEqual(self.client.post(self.pay_url, data).status_code, 403)
        self.assertEqual(self.client.post(reverse("vendor-payment-detail", args=[payment.pk]), {"action": "sync"}).status_code, 403)
        self.assertNotContains(self.client.get(self.detail_url), "Retry payment")
        transport.assert_not_called()

    @patch("payments.services.urlopen")
    def test_tampered_token_cannot_create_payment(self, transport):
        data = self.data()
        data["submission_token"] += "tampered"
        response = self.client.post(self.pay_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VendorPayment.objects.exists())
        transport.assert_not_called()

    @patch("payments.services.urlopen")
    def test_card_payment_uses_liability_funding(self, transport):
        data = self.data()
        data.update(payment_method="credit_card", credit_card_account_name="Card Liability")
        transport.return_value = self.posted()
        self.client.post(self.pay_url, data)
        payment = VendorPayment.objects.get()
        self.assertEqual(payment.bank_account_name, "")
        self.assertEqual(json.loads(transport.call_args.args[0].data)["funding_account_code"], "2100")

    @patch("payments.services.urlopen")
    def test_token_cannot_be_used_for_another_bill_or_user(self, transport):
        data = self.data()
        other_bill = VendorBill.objects.create(vendor=self.bill.vendor, property=self.bill.property,
            bill_date=date(2026, 5, 1), amount=Decimal("100.00"),
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE)
        response = self.client.post(reverse("vendor-bill-pay", args=[other_bill.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or expired")
        other_user = get_user_model().objects.create_user("another-bookkeeper")
        assign_user_role(other_user, ROLE_BOOKKEEPER)
        WorkflowAuthorizationService.set_grants(
            target=other_user, actor=self.grant_admin,
            can_approve_vendor_bills=False, can_pay_vendor_bills=True,
        )
        self.client.force_login(other_user)
        response = self.client.post(self.pay_url, data)
        self.assertContains(response, "invalid or expired")
        self.assertFalse(VendorPayment.objects.exists())
        transport.assert_not_called()

    @patch("payments.services.urlopen")
    def test_retry_button_returns_to_bill_and_reuses_failed_payment(self, transport):
        data = self.data()
        transport.side_effect = [URLError("timeout"), self.posted()]
        self.client.post(self.pay_url, data)
        payment = VendorPayment.objects.get()
        response = self.client.post(reverse("vendor-payment-detail", args=[payment.pk]), {"action": "sync"})
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertEqual(payment.status, VendorPayment.Status.POSTED)
        self.assertEqual(VendorPayment.objects.count(), 1)

    @patch("payments.services.urlopen")
    def test_bill_identity_and_payoff_flag_cannot_be_overridden(self, transport):
        data = self.data()
        data.update(vendor="999999", vendor_bill="999999", is_credit_card_payoff="on")
        transport.return_value = self.posted()
        self.client.post(self.pay_url, data)
        payment = VendorPayment.objects.get()
        self.assertEqual(payment.vendor_bill_id, self.bill.pk)
        self.assertEqual(payment.vendor_id, self.bill.vendor_id)
        self.assertFalse(payment.is_credit_card_payoff)


class BillPaymentConcurrencyTests(TransactionTestCase):
    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    @patch("payments.services.BillPaymentStatusService.statuses")
    def test_simultaneous_submissions_post_one_payment(self, statuses, transport):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from uuid import uuid4
        from django.db import close_old_connections
        from payments.services import VendorPaymentService
        _configure_ledgeros_settings()
        _configure_epic5_mappings()
        user_model = get_user_model()
        actor = user_model.objects.create_user("concurrent-payer")
        grant_admin = user_model.objects.create_user("concurrent-admin")
        assign_user_role(actor, ROLE_BOOKKEEPER)
        assign_user_role(grant_admin, ROLE_ADMIN)
        WorkflowAuthorizationService.set_grants(
            target=actor, actor=grant_admin,
            can_approve_vendor_bills=False, can_pay_vendor_bills=True,
        )
        vendor = Vendor.objects.create(name="Concurrent vendor")
        property_obj = Property.objects.create(name="Building", primary_owner=Owner.objects.create(name="Owner"))
        bill = VendorBill.objects.create(vendor=vendor, property=property_obj, bill_date=date(2026, 5, 1),
            amount=Decimal("100.00"), expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            status=VendorBill.Status.POSTED)
        bill.sync_record = LedgerOSSyncRecord.objects.create(
            local_object_type="vendor_bill", local_object_id=str(bill.pk), source_event_type="vendor_bill.created",
            external_id=f"vendor-bill:{bill.pk}", idempotency_key="concurrent-bill", request_hash="bill",
            ledgeros_resource_type="bill", status=LedgerOSSyncRecord.Status.SUCCEEDED)
        bill.save()
        bill.approval_status = VendorBill.ApprovalStatus.APPROVED
        bill.approved_fingerprint = VendorBillApprovalService.financial_fingerprint(bill)
        bill.save(update_fields=["approval_status", "approved_fingerprint", "updated_at"])
        statuses.return_value = {bill.pk: {"status": "unpaid", "balance": Decimal("100.00")}}
        transport.return_value = _FakeResponse(status=201, payload=json.dumps({"payment": {"id": 22},
            "journal_entry": {"id": 33, "status": "posted"}}).encode())
        submission_id = uuid4()
        barrier = Barrier(2)
        details = {"payment_date": date(2026, 5, 2), "amount": Decimal("100.00"), "payment_method": "ach_manual",
                   "bank_account_name": "Operating Bank", "credit_card_account_name": "", "memo": "", "notes": "", "check_number": None}

        def submit(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return VendorPaymentService.pay_bill(
                    bill=bill, submission_id=submission_id, details=details, actor=actor
                ).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            payment_ids = list(executor.map(submit, range(2)))
        self.assertEqual(payment_ids[0], payment_ids[1])
        self.assertEqual(VendorPayment.objects.count(), 1)
        self.assertEqual(transport.call_count, 1)
