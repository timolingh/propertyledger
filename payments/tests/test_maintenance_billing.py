from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSSyncRecord, Lease, Owner, Property, Tenant, Unit
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER, assign_user_role
from payments.maintenance_forms import MAINTENANCE_BILL_TOKEN_SALT
from payments.maintenance_services import MaintenanceBillHandoffService, MaintenanceRequestService
from payments.models import (
    MaintenanceCategory,
    MaintenanceRequest,
    MaintenanceRequestEvent,
    Vendor,
    VendorBill,
)


class MaintenanceBillingTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.admin = users.create_user("handoff-admin")
        self.manager = users.create_user("handoff-manager")
        self.bookkeeper = users.create_user("handoff-bookkeeper")
        assign_user_role(self.admin, ROLE_ADMIN)
        assign_user_role(self.manager, ROLE_PROPERTY_MANAGER)
        assign_user_role(self.bookkeeper, ROLE_BOOKKEEPER)

        owner = Owner.objects.create(name="Owner")
        self.property = Property.objects.create(name="Building", primary_owner=owner)
        self.other_property = Property.objects.create(name="Other", primary_owner=owner)
        self.unit = Unit.objects.create(property=self.property, name="1A")
        self.other_unit = Unit.objects.create(property=self.property, name="2B")
        self.tenant = Tenant.objects.create(name="Resident")
        Lease.objects.create(
            unit=self.unit,
            tenant=self.tenant,
            lease_start_date=date(2026, 1, 1),
            status=Lease.Status.ACTIVE,
        )
        self.category = MaintenanceCategory.objects.create(name="Plumbing")
        self.vendor = Vendor.objects.create(name="Plumber")
        self.second_vendor = Vendor.objects.create(name="Painter")
        self.request = MaintenanceRequestService.create(
            actor=self.manager,
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            category=self.category,
            priority=MaintenanceRequest.Priority.NORMAL,
            description="Repair kitchen leak",
            assigned_vendor=self.vendor,
            target_completion_date=None,
            estimated_cost=Decimal("500.00"),
        )

    def bill(self, *, vendor=None, property_obj=None, unit=None, status=VendorBill.Status.DRAFT):
        return VendorBill.objects.create(
            vendor=vendor or self.vendor,
            property=property_obj or self.property,
            unit=self.unit if unit is None else unit,
            bill_date=date(2026, 10, 21),
            amount=Decimal("100.00"),
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            maintenance_category=self.category,
            status=status,
            created_by=self.bookkeeper,
        )

    def close_request(self):
        request = self.request
        for action in ("triage", "assign", "start", "verify"):
            request = MaintenanceRequestService.transition(
                request=request,
                action=action,
                actor=self.manager,
                expected_version=request.version,
                assigned_vendor=self.vendor if action == "assign" else None,
                reason="Inspected" if action == "verify" else "",
            )
        self.request = MaintenanceRequestService.transition(
            request=request,
            action="close",
            actor=self.manager,
            expected_version=request.version,
            reason="Invoice pending",
            closure_financial_status=MaintenanceRequest.ClosureFinancialStatus.INVOICE_PENDING,
        )
        return self.request

    def test_manager_links_and_unlinks_compatible_existing_bill_with_audit(self):
        bill = self.bill()
        linked = MaintenanceBillHandoffService.link_bill(
            request=self.request,
            bill=bill,
            actor=self.manager,
            expected_version=self.request.version,
        )
        self.request.refresh_from_db()
        self.assertEqual(linked.maintenance_request, self.request)
        self.assertEqual(self.request.events.last().action, MaintenanceRequestEvent.Action.BILL_LINKED)
        self.assertEqual(self.request.events.last().metadata["bill_id"], bill.pk)

        MaintenanceBillHandoffService.unlink_bill(
            request=self.request,
            bill=linked,
            actor=self.manager,
            expected_version=self.request.version,
        )
        bill.refresh_from_db()
        self.request.refresh_from_db()
        self.assertIsNone(bill.maintenance_request)
        self.assertEqual(self.request.events.last().action, MaintenanceRequestEvent.Action.BILL_UNLINKED)

    def test_link_rejects_property_unit_and_existing_request_mismatches(self):
        wrong_property_bill = self.bill(property_obj=self.other_property, unit=None)
        with self.assertRaises(ValidationError):
            MaintenanceBillHandoffService.link_bill(
                request=self.request,
                bill=wrong_property_bill,
                actor=self.manager,
                expected_version=self.request.version,
            )
        wrong_unit_bill = self.bill(vendor=self.second_vendor, unit=self.other_unit)
        with self.assertRaises(ValidationError):
            MaintenanceBillHandoffService.link_bill(
                request=self.request,
                bill=wrong_unit_bill,
                actor=self.manager,
                expected_version=self.request.version,
            )

        other_request = MaintenanceRequestService.create(
            actor=self.manager,
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            category=self.category,
            priority=MaintenanceRequest.Priority.LOW,
            description="Other work",
            assigned_vendor=None,
            target_completion_date=None,
            estimated_cost=None,
        )
        compatible = self.bill(vendor=self.second_vendor)
        MaintenanceBillHandoffService.link_bill(
            request=other_request,
            bill=compatible,
            actor=self.manager,
            expected_version=other_request.version,
        )
        with self.assertRaises(ValidationError):
            MaintenanceBillHandoffService.link_bill(
                request=self.request,
                bill=compatible,
                actor=self.manager,
                expected_version=self.request.version,
            )

    def test_multiple_vendor_bills_can_be_linked_after_closure_without_reopening(self):
        request = self.close_request()
        self.client.force_login(self.manager)
        home = self.client.get(reverse("app-home"))
        self.assertContains(home, "Maintenance awaiting vendor bill")
        self.assertContains(home, reverse("maintenance-request-detail", args=[request.pk]))
        bills = [self.bill(), self.bill(vendor=self.second_vendor)]
        for bill in bills:
            MaintenanceBillHandoffService.link_bill(
                request=request,
                bill=bill,
                actor=self.manager,
                expected_version=request.version,
            )
            request.refresh_from_db()

        self.assertEqual(request.status, MaintenanceRequest.Status.CLOSED)
        self.assertEqual(request.vendor_bills.count(), 2)
        self.assertEqual(request.events.filter(action=MaintenanceRequestEvent.Action.BILL_LINKED).count(), 2)

    def test_manager_may_link_but_cannot_create_vendor_bill(self):
        bill = self.bill()
        MaintenanceBillHandoffService.link_bill(
            request=self.request,
            bill=bill,
            actor=self.manager,
            expected_version=self.request.version,
        )
        candidate = VendorBill(
            vendor=self.vendor,
            property=self.property,
            unit=self.unit,
            bill_date=date(2026, 10, 21),
            amount=Decimal("125.00"),
            expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
        )
        with self.assertRaises(PermissionDenied):
            MaintenanceBillHandoffService.create_bill(
                request=self.request,
                bill=candidate,
                actor=self.manager,
                expected_version=self.request.version,
                submission_id="14ca0acd-55eb-4ff9-bd0b-67bbaa4336fa",
            )

    def test_prefill_get_creates_nothing_and_duplicate_post_reuses_bill(self):
        self.client.force_login(self.bookkeeper)
        create_url = reverse("maintenance-bill-create", args=[self.request.pk])
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VendorBill.objects.exists())
        token = response.context["handoff_token"]
        token_data = signing.loads(token, salt=MAINTENANCE_BILL_TOKEN_SALT)
        self.assertEqual(token_data["request_id"], self.request.pk)

        payload = {
            "handoff_token": token,
            "vendor": self.vendor.pk,
            "property": self.property.pk,
            "unit": self.unit.pk,
            "bill_date": "2026-10-21",
            "due_date": "2026-11-01",
            "amount": "500.00",
            "expense_category": VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            "maintenance_category": self.category.pk,
            "repair_notes": "Leak repair",
            "tenant_chargeable": "",
            "notes": "Invoice 100",
            "action": "draft",
        }
        first = self.client.post(create_url, payload)
        second = self.client.post(create_url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(VendorBill.objects.count(), 1)
        bill = VendorBill.objects.get()
        self.assertEqual(bill.maintenance_request, self.request)
        self.assertEqual(str(bill.maintenance_submission_id), token_data["submission_id"])
        self.assertEqual(bill.status, VendorBill.Status.DRAFT)
        self.assertIsNone(bill.sync_record)
        self.assertEqual(
            self.request.events.filter(action=MaintenanceRequestEvent.Action.BILL_LINKED).count(),
            1,
        )

    def test_submitted_handoff_is_not_resubmitted_on_repeated_post(self):
        self.client.force_login(self.bookkeeper)
        response = self.client.get(reverse("maintenance-bill-create", args=[self.request.pk]))
        token = response.context["handoff_token"]
        payload = {
            "handoff_token": token,
            "vendor": self.vendor.pk,
            "property": self.property.pk,
            "unit": self.unit.pk,
            "bill_date": "2026-10-21",
            "due_date": "",
            "amount": "500.00",
            "expense_category": VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            "maintenance_category": self.category.pk,
            "repair_notes": "Leak repair",
            "tenant_chargeable": "",
            "notes": "",
            "action": "submit",
        }
        url = reverse("maintenance-bill-create", args=[self.request.pk])
        self.client.post(url, payload)
        self.client.post(url, payload)
        bill = VendorBill.objects.get()
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.SUBMITTED)
        self.assertEqual(bill.submission_version, 1)

    def test_posted_bill_link_is_operational_and_does_not_change_accounting_or_request_state(self):
        request = self.close_request()
        bill = self.bill(status=VendorBill.Status.POSTED)
        bill.sync_record = LedgerOSSyncRecord.objects.create(
            local_object_type="vendor_bill",
            local_object_id=str(bill.pk),
            source_event_type="vendor_bill.created",
            external_id=f"vendor-bill:{bill.pk}",
            idempotency_key=f"bill:{bill.pk}",
            request_hash="original",
            ledgeros_resource_type="bill",
            ledgeros_resource_id="55",
            ledgeros_journal_entry_id="88",
            status=LedgerOSSyncRecord.Status.SUCCEEDED,
        )
        bill.save(update_fields=["sync_record", "updated_at"])

        MaintenanceBillHandoffService.link_bill(
            request=request,
            bill=bill,
            actor=self.manager,
            expected_version=request.version,
        )
        bill.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(request.status, MaintenanceRequest.Status.CLOSED)
        self.assertEqual(bill.status, VendorBill.Status.POSTED)
        self.assertEqual(bill.sync_record.request_hash, "original")
        self.assertEqual(bill.sync_record.ledgeros_journal_entry_id, "88")

    def test_link_ui_enforces_manager_authority_and_shows_separate_bill_states(self):
        bill = self.bill()
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("maintenance-bill-link", args=[self.request.pk]),
            {"bill": bill.pk, "version": self.request.version},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(reverse("maintenance-bill-create", args=[self.request.pk])).status_code,
            403,
        )
        detail = self.client.get(reverse("maintenance-request-detail", args=[self.request.pk]))
        self.assertContains(detail, "Approval")
        self.assertContains(detail, "Posting")
        self.assertContains(detail, "Payment")
        self.assertContains(detail, reverse("vendor-bill-detail", args=[bill.pk]))

    @patch("payments.maintenance_views.BillPaymentStatusService.statuses")
    def test_detail_shows_partial_payment_without_changing_maintenance_state(self, statuses):
        bill = self.bill()
        MaintenanceBillHandoffService.link_bill(
            request=self.request,
            bill=bill,
            actor=self.manager,
            expected_version=self.request.version,
        )
        statuses.return_value = {
            bill.pk: {
                "status": "partially_paid",
                "label": "Partially paid",
                "paid": Decimal("40.00"),
                "credited": Decimal("0.00"),
                "balance": Decimal("60.00"),
                "error": "",
            }
        }
        self.client.force_login(self.manager)
        response = self.client.get(reverse("maintenance-request-detail", args=[self.request.pk]))
        self.assertContains(response, "Partially paid")
        self.assertContains(response, "Balance 60.00")
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, MaintenanceRequest.Status.OPEN)

