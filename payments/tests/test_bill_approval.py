from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from ledgeros.models import AuditLog, LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, assign_user_role
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.models import Vendor, VendorBill, VendorBillApprovalEvent
from payments.services import SyncResult, VendorBillService, VendorPaymentService


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

    def approved_bill(self):
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        return VendorBillApprovalService.approve(bill, actor=self.approver, reason="Checked")

    def test_withdraw_approved_bill_preserves_history_and_requires_reapproval(self):
        for actor in (self.submitter, self.admin):
            with self.subTest(actor=actor.username):
                bill = self.approved_bill()
                with patch("payments.services.LedgerOSSyncEventService._submit") as transport:
                    bill = VendorBillApprovalService.withdraw(bill, actor=actor, reason="  Duplicate invoice  ")
                    self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.WITHDRAWN)
                    self.assertEqual(bill.status, VendorBill.Status.DRAFT)
                    self.assertIsNone(bill.sync_record_id)
                    self.assertEqual(bill.approved_fingerprint, "")
                    self.assertEqual(bill.decision_by, actor)
                    self.assertEqual(bill.decision_reason, "Duplicate invoice")
                    self.assertEqual(bill.submission_version, 1)
                    self.assertEqual(list(bill.approval_events.values_list("action", flat=True)),
                                     ["submitted", "approved", "withdrawn"])
                    original = bill.approval_events.get(action="approved")
                    self.assertEqual(original.actor, self.approver)
                    self.assertEqual(original.reason, "Checked")
                    self.assertTrue(original.financial_fingerprint)
                    self.assertTrue(AuditLog.objects.filter(
                        action="vendor_bill_withdrawn", record_id=str(bill.pk), actor=actor,
                    ).exists())
                    with self.assertRaisesMessage(ValidationError, "explicitly approved"):
                        VendorBillService.sync_bill(bill, actor=self.submitter)
                    self.assertIn("explicitly approved", VendorPaymentService.bill_payment_blocker(bill, {}))
                    transport.assert_not_called()
                VendorBillApprovalService.submit(bill, actor=self.submitter)
                bill = VendorBillApprovalService.approve(bill, actor=self.approver)
                self.assertEqual(bill.submission_version, 2)
                self.assertTrue(bill.approved_fingerprint)

    def test_approved_withdrawal_requires_reason_and_original_authority(self):
        bill = self.approved_bill()
        with self.assertRaisesMessage(ValidationError, "reason is required"):
            VendorBillApprovalService.withdraw(bill, actor=self.submitter, reason="  ")
        for actor in (self.approver, self.payer):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                VendorBillApprovalService.withdraw(bill, actor=actor, reason="Changed mind")
        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.APPROVED)
        self.assertEqual(bill.approval_events.count(), 2)

    def test_approved_withdrawal_blocks_posted_and_attempted_bills(self):
        for status in (LedgerOSSyncRecord.Status.FAILED, LedgerOSSyncRecord.Status.IN_PROGRESS,
                       LedgerOSSyncRecord.Status.SUCCEEDED):
            with self.subTest(status=status):
                bill = self.approved_bill()
                bill.sync_record = LedgerOSSyncRecord.objects.create(
                    local_object_type="vendor_bill", local_object_id=str(bill.pk),
                    source_event_type="vendor_bill.created", external_id=f"vendor-bill:{bill.pk}",
                    idempotency_key=f"bill:{bill.pk}", request_hash="original", status=status,
                    attempt_count=1,
                )
                bill.save(update_fields=["sync_record"])
                with self.assertRaisesMessage(ValidationError, "posting has started"):
                    VendorBillApprovalService.withdraw(bill, actor=self.admin, reason="Cancel")
                bill.refresh_from_db()
                self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.APPROVED)
                self.assertEqual(bill.approval_events.count(), 2)
        bill = self.approved_bill()
        bill.status = VendorBill.Status.POSTED
        bill.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            VendorBillApprovalService.withdraw(bill, actor=self.admin, reason="Cancel")

    def test_approved_withdrawal_ui_and_direct_post_permissions(self):
        bill = self.approved_bill()
        url = reverse("vendor-bill-detail", args=[bill.pk])
        for actor in (self.approver, self.payer):
            self.client.force_login(actor)
            self.assertNotContains(self.client.get(url), "Withdraw approved bill")
            self.assertEqual(self.client.post(url, {"action": "withdraw", "reason": "Cancel"}).status_code, 403)
        self.client.force_login(self.submitter)
        self.assertContains(self.client.get(url), "Withdraw approved bill")
        response = self.client.post(url, {"action": "withdraw", "reason": " "}, follow=True)
        self.assertContains(response, "A withdrawal reason is required.")
        response = self.client.post(url, {"action": "withdraw", "reason": "Duplicate"}, follow=True)
        self.assertContains(response, "Submit for approval")
        self.assertNotContains(response, "Post approved bill")
        bill.refresh_from_db()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.WITHDRAWN)

    def test_submitted_withdrawal_still_allows_no_reason(self):
        bill = VendorBillApprovalService.save_draft(self.bill(), actor=self.submitter)
        VendorBillApprovalService.submit(bill, actor=self.submitter)
        bill = VendorBillApprovalService.withdraw(bill, actor=self.submitter)
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.WITHDRAWN)

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
    def test_withdrawal_and_posting_recheck_state_under_the_same_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        users = get_user_model().objects
        submitter = users.create_user("withdraw-submitter")
        approver = users.create_user("withdraw-approver")
        assign_user_role(submitter, ROLE_BOOKKEEPER)
        assign_user_role(approver, ROLE_ADMIN)
        WorkflowAuthorizationService.set_grants(
            target=approver, actor=approver,
            can_approve_vendor_bills=True, can_pay_vendor_bills=False,
        )
        vendor = Vendor.objects.create(name="Withdrawal vendor")
        property_obj = Property.objects.create(
            name="Withdrawal building", primary_owner=Owner.objects.create(name="Owner")
        )
        for first in ("withdraw", "post"):
            with self.subTest(first=first):
                bill = VendorBillApprovalService.save_draft(VendorBill(
                    vendor=vendor, property=property_obj, amount=Decimal("100.00"),
                    expense_category=VendorBill.ExpenseCategory.OTHER,
                ), actor=submitter)
                VendorBillApprovalService.submit(bill, actor=submitter)
                bill = VendorBillApprovalService.approve(bill, actor=approver)
                locked, contender_started = Event(), Event()

                def act(action, *, hold_lock=False):
                    close_old_connections()
                    try:
                        with transaction.atomic():
                            if hold_lock:
                                VendorBill.objects.select_for_update().get(pk=bill.pk)
                                locked.set()
                                if not contender_started.wait(timeout=10):
                                    raise AssertionError("Contender did not start")
                            else:
                                if not locked.wait(timeout=10):
                                    raise AssertionError("First operation did not lock bill")
                                contender_started.set()
                            if action == "withdraw":
                                VendorBillApprovalService.withdraw(bill, actor=submitter, reason="Duplicate")
                            else:
                                VendorBillService.sync_bill(bill, actor=submitter)
                        return action
                    except ValidationError:
                        return "blocked"
                    finally:
                        close_old_connections()

                with patch.object(VendorBillService, "_sync_blockers", return_value=[]), \
                     patch("payments.services.LedgerOSVendorBillService._build_bill_payload", return_value={"amount": "100.00"}), \
                     patch("payments.services.LedgerOSSyncEventService._submit", return_value=SyncResult(
                         status_code=201, payload={"bill": {"id": 42}, "journal_entry": {"id": 43}},
                     )) as transport, ThreadPoolExecutor(max_workers=2) as executor:
                    winner = executor.submit(act, first, hold_lock=True)
                    loser = executor.submit(act, "post" if first == "withdraw" else "withdraw")
                    self.assertEqual(winner.result(timeout=20), first)
                    self.assertEqual(loser.result(timeout=20), "blocked")
                    self.assertEqual(transport.call_count, int(first == "post"))
                bill.refresh_from_db()
                self.assertEqual(bill.approval_status, "withdrawn" if first == "withdraw" else "approved")
                self.assertEqual(bill.status, "draft" if first == "withdraw" else "posted")

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

