from datetime import date
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER, assign_user_role
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.authorization import can_approve_vendor_bills, can_pay_vendor_bills
from payments.models import Vendor, VendorBill, VendorPayment
from payments.admin import VendorPaymentAdmin
from payments.services import SyncResult, VendorPaymentService
from payments.tests.test_payments_workflow import _configure_epic5_mappings, _configure_ledgeros_settings


class WorkflowAuthorizationTests(TestCase):
    def setUp(self):
        readiness = patch("payments.views.LedgerOSWriteReadinessService.require")
        readiness.start()
        self.addCleanup(readiness.stop)
        _configure_ledgeros_settings()
        _configure_epic5_mappings()
        users = get_user_model().objects
        self.admin = users.create_user("admin")
        self.submitter = users.create_user("submitter")
        self.approver = users.create_user("approver")
        self.payer = users.create_user("payer")
        assign_user_role(self.admin, ROLE_ADMIN)
        assign_user_role(self.submitter, ROLE_BOOKKEEPER)
        assign_user_role(self.approver, ROLE_PROPERTY_MANAGER)
        assign_user_role(self.payer, ROLE_PROPERTY_MANAGER)
        self.property = Property.objects.create(
            name="Building", primary_owner=Owner.objects.create(name="Owner")
        )
        self.vendor = Vendor.objects.create(name="Vendor")

    def grant(self, user, *, approve=False, pay=False):
        return WorkflowAuthorizationService.set_grants(
            target=user,
            actor=self.admin,
            can_approve_vendor_bills=approve,
            can_pay_vendor_bills=pay,
        )

    def approved_bill(self):
        self.grant(self.approver, approve=True)
        bill = VendorBillApprovalService.save_draft(
            VendorBill(
                vendor=self.vendor,
                property=self.property,
                bill_date=date(2026, 10, 1),
                amount=Decimal("100.00"),
                expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            ),
            actor=self.submitter,
        )
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        VendorBillApprovalService.approve(bill, actor=self.approver)
        bill.status = VendorBill.Status.POSTED
        bill.sync_record = LedgerOSSyncRecord.objects.create(
            local_object_type="vendor_bill",
            local_object_id=str(bill.pk),
            source_event_type="vendor_bill.created",
            external_id=f"vendor-bill:{bill.pk}",
            idempotency_key=f"bill:{bill.pk}",
            request_hash="bill",
            ledgeros_resource_type="bill",
            status=LedgerOSSyncRecord.Status.SUCCEEDED,
        )
        bill.save(update_fields=["status", "sync_record", "updated_at"])
        return bill

    def test_grants_are_independent_and_require_active_workflow_role(self):
        self.grant(self.approver, approve=True)
        self.assertTrue(can_approve_vendor_bills(self.approver))
        self.assertFalse(can_pay_vendor_bills(self.approver))
        self.grant(self.payer, pay=True)
        self.assertFalse(can_approve_vendor_bills(self.payer))
        self.assertTrue(can_pay_vendor_bills(self.payer))
        self.payer.is_active = False
        self.payer.save(update_fields=["is_active"])
        self.assertFalse(can_pay_vendor_bills(self.payer))

    def test_only_admin_can_change_grants(self):
        with self.assertRaises(PermissionDenied):
            WorkflowAuthorizationService.set_grants(
                target=self.payer,
                actor=self.submitter,
                can_approve_vendor_bills=False,
                can_pay_vendor_bills=True,
            )

    def test_admin_grant_page_and_approval_ui_enforce_independent_capabilities(self):
        self.client.force_login(self.submitter)
        self.assertEqual(self.client.get(reverse("workflow-authorizations")).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("workflow-authorizations"),
            {"user": self.approver.pk, "can_approve_vendor_bills": "on"},
        )
        self.assertEqual(response.status_code, 302)

        bill = VendorBillApprovalService.save_draft(
            VendorBill(
                vendor=self.vendor, property=self.property, bill_date=date(2026, 10, 1),
                amount=Decimal("100.00"),
                expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            ), actor=self.submitter,
        )
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        self.client.force_login(self.approver)
        queue = self.client.get(reverse("vendor-bill-approval-queue"))
        self.assertContains(queue, reverse("vendor-bill-detail", args=[bill.pk]))
        response = self.client.post(
            reverse("vendor-bill-detail", args=[bill.pk]),
            {"action": "approve", "reason": "Reviewed"},
        )
        self.assertEqual(response.status_code, 302)
        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.APPROVED)

    def test_ungranted_user_and_admin_model_cannot_bypass_payment_service(self):
        bill = self.approved_bill()
        self.client.force_login(self.payer)
        self.assertEqual(
            self.client.get(reverse("vendor-bill-pay", args=[bill.pk])).status_code,
            403,
        )
        request = RequestFactory().post("/admin/payments/vendorpayment/add/")
        request.user = self.admin
        payment = VendorPayment(
            vendor=self.vendor,
            vendor_bill=bill,
            payment_date=date(2026, 10, 2),
            amount=Decimal("100.00"),
            payment_method=VendorPayment.PaymentMethod.ACH_MANUAL,
            bank_account_name="Operating Bank",
        )
        with self.assertRaises(PermissionDenied):
            VendorPaymentAdmin(VendorPayment, django_admin.site).save_model(
                request, payment, form=None, change=False
            )

    def test_generic_payment_create_cannot_bypass_bill_scoped_submission_identity(self):
        bill = self.approved_bill()
        self.grant(self.submitter, pay=True)
        self.client.force_login(self.submitter)
        response = self.client.post(
            reverse("vendor-payment-create"),
            {
                "vendor": self.vendor.pk,
                "vendor_bill": bill.pk,
                "payment_date": "2026-10-02",
                "amount": "100.00",
                "payment_method": VendorPayment.PaymentMethod.ACH_MANUAL,
                "bank_account_name": "Operating Bank",
                "credit_card_account_name": "",
                "memo": "",
                "check_number": "",
                "check_status": VendorPayment.CheckStatus.NOT_APPLICABLE,
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start a new vendor settlement from the approved bill")
        self.assertFalse(VendorPayment.objects.exists())

    @patch("payments.services.BillPaymentStatusService.statuses")
    @patch("payments.services.VendorPaymentService.sync_payment")
    def test_new_payment_requires_approval_and_payment_grant(self, sync_payment, statuses):
        bill = self.approved_bill()
        statuses.return_value = {bill.pk: {"status": "unpaid", "balance": Decimal("100.00")}}
        sync_payment.side_effect = lambda payment, **kwargs: payment
        details = {
            "payment_date": date(2026, 10, 2),
            "amount": Decimal("100.00"),
            "payment_method": VendorPayment.PaymentMethod.ACH_MANUAL,
            "bank_account_name": "Operating Bank",
            "credit_card_account_name": "",
            "memo": "",
            "check_number": None,
            "notes": "",
        }
        with self.assertRaises(PermissionDenied):
            VendorPaymentService.pay_bill(
                bill=bill, submission_id=uuid4(), details=details, actor=self.payer
            )
        self.grant(self.payer, pay=True)
        payment = VendorPaymentService.pay_bill(
            bill=bill, submission_id=uuid4(), details=details, actor=self.payer
        )
        self.assertEqual(payment.initiated_by, self.payer)

        bill.approval_status = VendorBill.ApprovalStatus.REJECTED
        bill.save(update_fields=["approval_status", "updated_at"])
        with self.assertRaises(ValidationError):
            VendorPaymentService.pay_bill(
                bill=bill, submission_id=uuid4(), details=details, actor=self.payer
            )

    @patch("payments.services.BillPaymentStatusService.statuses")
    def test_revoked_user_cannot_retry_but_another_authorized_user_reuses_identity(self, statuses):
        bill = self.approved_bill()
        self.grant(self.payer, pay=True)
        statuses.return_value = {bill.pk: {"status": "unpaid", "balance": Decimal("100.00")}}
        details = {
            "payment_date": date(2026, 10, 2), "amount": Decimal("100.00"),
            "payment_method": VendorPayment.PaymentMethod.ACH_MANUAL,
            "bank_account_name": "Operating Bank", "credit_card_account_name": "",
            "memo": "", "check_number": None, "notes": "",
        }
        with patch("payments.services.LedgerOSSyncEventService._submit", side_effect=RuntimeError("timeout")):
            payment = VendorPaymentService.pay_bill(
                bill=bill, submission_id=uuid4(), details=details, actor=self.payer
            )
        first_key = payment.sync_record.idempotency_key
        self.grant(self.payer, pay=False)
        with self.assertRaises(PermissionDenied):
            VendorPaymentService.sync_payment(payment, actor=self.payer)

        replacement = get_user_model().objects.create_user("replacement-payer")
        assign_user_role(replacement, ROLE_BOOKKEEPER)
        self.grant(replacement, pay=True)
        result = SyncResult(
            status_code=201,
            payload={"payment": {"id": 44}, "journal_entry": {"id": 55, "status": "posted"}},
        )
        with patch("payments.services.LedgerOSSyncEventService._submit", return_value=result):
            VendorPaymentService.sync_payment(payment, actor=replacement)
        payment.refresh_from_db()
        self.assertEqual(payment.sync_record.idempotency_key, first_key)
        self.assertEqual(payment.status, VendorPayment.Status.POSTED)

