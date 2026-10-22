from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, assign_user_role
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.models import Vendor, VendorBill, VendorBillApprovalEvent


class VendorBillApprovalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.submitter = user_model.objects.create_user("submitter")
        self.approver = user_model.objects.create_user("approver")
        self.payer = user_model.objects.create_user("payer")
        self.admin = user_model.objects.create_user("grant-admin")
        for user in (self.submitter, self.approver, self.payer):
            assign_user_role(user, ROLE_BOOKKEEPER)
        assign_user_role(self.admin, ROLE_ADMIN)
        WorkflowAuthorizationService.set_grants(
            target=self.approver,
            actor=self.admin,
            can_approve_vendor_bills=True,
            can_pay_vendor_bills=False,
        )
        self.property = Property.objects.create(
            name="Building", primary_owner=Owner.objects.create(name="Owner")
        )
        self.vendor = Vendor.objects.create(name="Vendor")

    def bill(self):
        return VendorBill(
            vendor=self.vendor,
            property=self.property,
            bill_date=date(2026, 10, 1),
            amount=Decimal("125.00"),
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
        )

    def test_submitter_cannot_approve_even_with_grant(self):
        WorkflowAuthorizationService.set_grants(
            target=self.submitter,
            actor=self.admin,
            can_approve_vendor_bills=True,
            can_pay_vendor_bills=False,
        )
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)

        with self.assertRaises(PermissionDenied):
            VendorBillApprovalService.approve(bill, actor=self.submitter)

        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.SUBMITTED)

    def test_independent_approver_records_version_fingerprint_and_history(self):
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        VendorBillApprovalService.approve(bill, actor=self.approver, reason="Invoice checked")

        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.APPROVED)
        self.assertEqual(bill.submitted_by, self.submitter)
        self.assertEqual(bill.decision_by, self.approver)
        self.assertTrue(bill.approved_fingerprint)
        self.assertEqual(
            list(bill.approval_events.values_list("action", flat=True)),
            [VendorBill.ApprovalStatus.SUBMITTED, VendorBill.ApprovalStatus.APPROVED],
        )

    def test_submitted_bill_cannot_change_and_financial_change_invalidates_approval(self):
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        bill.amount = Decimal("130.00")
        with self.assertRaises(ValidationError):
            VendorBillApprovalService.save_draft(bill, actor=self.submitter)

        bill.refresh_from_db()
        VendorBillApprovalService.approve(bill, actor=self.approver)
        bill.amount = Decimal("130.00")
        VendorBillApprovalService.save_draft(bill, actor=self.submitter)
        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.DRAFT)
        self.assertEqual(bill.approved_fingerprint, "")

    def test_rejection_requires_reason_and_allows_correction_and_resubmission(self):
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        with self.assertRaises(ValidationError):
            VendorBillApprovalService.reject(bill, actor=self.approver, reason="")
        VendorBillApprovalService.reject(bill, actor=self.approver, reason="Wrong amount")
        bill.refresh_from_db()
        bill.amount = Decimal("100.00")
        VendorBillApprovalService.save_draft(bill, actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        bill.refresh_from_db()
        self.assertEqual(bill.submission_version, 2)

    def test_legacy_posted_bill_gets_prospective_approval_without_reposting(self):
        bill = VendorBill.objects.create(
            vendor=self.vendor,
            property=self.property,
            bill_date=date(2026, 10, 1),
            amount=Decimal("125.00"),
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            status=VendorBill.Status.POSTED,
            approval_status=VendorBill.ApprovalStatus.LEGACY_UNRECORDED,
        )
        bill.sync_record = LedgerOSSyncRecord.objects.create(
            local_object_type="vendor_bill",
            local_object_id=str(bill.pk),
            source_event_type="vendor_bill.created",
            external_id=f"vendor-bill:{bill.pk}",
            idempotency_key="legacy-bill",
            request_hash="legacy",
            ledgeros_resource_type="bill",
            status=LedgerOSSyncRecord.Status.SUCCEEDED,
        )
        bill.save(update_fields=["sync_record", "updated_at"])

        VendorBillApprovalService.submit(bill, actor=self.submitter)
        VendorBillApprovalService.approve(bill, actor=self.approver)
        bill.refresh_from_db()
        self.assertEqual(bill.status, VendorBill.Status.POSTED)
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.APPROVED)
        self.assertEqual(VendorBillApprovalEvent.objects.filter(bill=bill).count(), 2)


class VendorBillApprovalConcurrencyTests(TransactionTestCase):
    def test_two_approvers_cannot_record_two_decisions_for_one_submission(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        users = get_user_model().objects
        admin = users.create_user("concurrent-admin")
        submitter = users.create_user("concurrent-submitter")
        approvers = [users.create_user(f"concurrent-approver-{index}") for index in range(2)]
        assign_user_role(admin, ROLE_ADMIN)
        assign_user_role(submitter, ROLE_BOOKKEEPER)
        for approver in approvers:
            assign_user_role(approver, ROLE_BOOKKEEPER)
            WorkflowAuthorizationService.set_grants(
                target=approver, actor=admin,
                can_approve_vendor_bills=True, can_pay_vendor_bills=False,
            )
        property_obj = Property.objects.create(
            name="Concurrent building", primary_owner=Owner.objects.create(name="Concurrent owner")
        )
        bill = VendorBillApprovalService.save_draft(
            VendorBill(
                vendor=Vendor.objects.create(name="Concurrent vendor"),
                property=property_obj,
                bill_date=date(2026, 10, 1),
                amount=Decimal("100.00"),
                expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            ),
            actor=submitter,
        )
        VendorBillApprovalService.submit(bill, actor=submitter)
        barrier = Barrier(2)

        def approve(approver):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                VendorBillApprovalService.approve(bill, actor=approver)
                return "approved"
            except ValidationError:
                return "state_rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, approvers))

        self.assertCountEqual(outcomes, ["approved", "state_rejected"])
        self.assertEqual(
            VendorBillApprovalEvent.objects.filter(
                bill=bill, action=VendorBill.ApprovalStatus.APPROVED
            ).count(),
            1,
        )

