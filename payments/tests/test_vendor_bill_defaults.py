from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_BOOKKEEPER, assign_user_role
from payments.approval_services import VendorBillApprovalService
from payments.forms import VendorBillForm, VendorForm
from payments.models import Vendor, VendorBill
from payments.services import LedgerOSVendorBillService, TenantPaymentService


class VendorBillDefaultsTests(TestCase):
    def setUp(self):
        self.vendor = Vendor.objects.create(name="Plumber")
        self.property = Property.objects.create(name="Building", primary_owner=Owner.objects.create(name="Owner"))
        self.actor = get_user_model().objects.create_user("bookkeeper")
        assign_user_role(self.actor, ROLE_BOOKKEEPER)

    def data(self, **overrides):
        return {"vendor": self.vendor.pk, "property": self.property.pk,
                "bill_date": "2026-12-20", "due_date": "", "amount": "100.00",
                "expense_category": "repairs_and_maintenance", "vendor_invoice_number": "INV-001", **overrides}

    def test_vendor_terms_and_new_bill_initial_dates(self):
        self.assertIn("payment_terms", VendorForm().fields)
        with patch("payments.forms.timezone.localdate", return_value=date(2026, 12, 20)):
            form = VendorBillForm()
        self.assertEqual(form.initial["bill_date"], date(2026, 12, 20))
        self.assertEqual(form.initial["due_date"], date(2026, 12, 20))

    def test_terms_defaults_and_explicit_dates(self):
        for days in (None, 0, 15, 30):
            with self.subTest(days=days):
                self.vendor.payment_terms = days
                self.vendor.save()
                form = VendorBillForm(data=self.data())
                self.assertTrue(form.is_valid(), form.errors)
                bill = VendorBillApprovalService.save_draft(form.save(commit=False), actor=self.actor)
                self.assertEqual(bill.due_date, date(2026, 12, 20) + timedelta(days=days or 0))
                self.assertEqual(bill.vendor_invoice_number, "INV-001")
                override = VendorBillForm(data=self.data(due_date="2027-02-01"))
                self.assertTrue(override.is_valid(), override.errors)
                self.assertEqual(override.cleaned_data["due_date"], date(2027, 2, 1))

    def test_service_defaults_and_existing_dates_remain_unchanged(self):
        self.vendor.payment_terms = 30
        self.vendor.save()
        bill = VendorBill(vendor=self.vendor, property=self.property, bill_date=date(2026, 12, 20),
                          amount="100.00", expense_category="other")
        bill = VendorBillApprovalService.save_draft(bill, actor=self.actor)
        self.assertEqual(bill.due_date, date(2027, 1, 19))
        self.vendor.payment_terms = 15
        self.vendor.save()
        form = VendorBillForm(instance=bill)
        self.assertEqual(form.initial["due_date"], date(2027, 1, 19))

    def test_maintenance_prefill_and_date_script_are_available(self):
        self.vendor.payment_terms = 15
        self.vendor.save()
        form = VendorBillForm(initial={"vendor": self.vendor, "bill_date": date(2026, 12, 20)})
        self.assertEqual(form.initial["due_date"], date(2027, 1, 4))
        self.assertIn('data-payment-days="15"', str(form["vendor"]))
        self.assertIn("payments/vendor_bill_dates.js", str(form.media))
        self.assertFalse(form.fields["bill_date"].disabled)
        self.assertFalse(form.fields["due_date"].disabled)

    def test_empty_invoice_number_preserves_historical_approval_fingerprint(self):
        bill = VendorBill(vendor=self.vendor, property=self.property, bill_date=date(2026, 12, 20))
        values = {}
        for field in VendorBillApprovalService.FINANCIAL_FIELDS:
            if field == "vendor_invoice_number":
                continue
            value = getattr(bill, field)
            values[field] = value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None
        old_hash = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(VendorBillApprovalService.financial_fingerprint(bill), old_hash)

    @patch("payments.services.Epic5AccountingService._account_code", return_value="5000")
    def test_supplier_invoice_payload_and_legacy_retry_compatibility(self, account_code):
        bill = VendorBill(pk=42, vendor=self.vendor, property=self.property,
                          bill_date=date(2026, 12, 20), amount=Decimal("100.00"), expense_category="other")
        legacy = LedgerOSVendorBillService._build_bill_payload(bill)
        self.assertNotIn("supplier_invoice_number", legacy)
        bill.vendor_invoice_number = "SUP-42"
        payload = LedgerOSVendorBillService._build_bill_payload(bill)
        self.assertEqual(payload["supplier_invoice_number"], "SUP-42")
        self.assertEqual(payload["external_bill_number"], "vendor-bill:42")
        self.assertEqual({k: v for k, v in payload.items() if k != "supplier_invoice_number"}, legacy)
        bill.sync_record = LedgerOSSyncRecord(attempt_count=1, request_hash=TenantPaymentService._sync_record_payload(legacy))
        self.assertEqual(LedgerOSVendorBillService._build_bill_payload(bill), legacy)
        bill.sync_record.request_hash = TenantPaymentService._sync_record_payload(payload)
        self.assertEqual(LedgerOSVendorBillService._build_bill_payload(bill), payload)
        bill.vendor_invoice_number = "CHANGED"
        with self.assertRaises(ValidationError):
            LedgerOSVendorBillService._build_bill_payload(bill)

    def test_invoice_number_edit_invalidates_approval_and_is_locked_after_posting(self):
        form = VendorBillForm(data=self.data())
        self.assertTrue(form.is_valid(), form.errors)
        bill = VendorBillApprovalService.save_draft(form.save(commit=False), actor=self.actor)
        bill.approval_status = VendorBill.ApprovalStatus.APPROVED
        bill.approved_fingerprint = VendorBillApprovalService.financial_fingerprint(bill)
        bill.save()
        bill.vendor_invoice_number = "INV-002"
        bill = VendorBillApprovalService.save_draft(bill, actor=self.actor)
        self.assertEqual(bill.approval_status, VendorBill.ApprovalStatus.DRAFT)
        self.assertEqual(bill.vendor_invoice_number, "INV-002")
        bill.status = VendorBill.Status.POSTED
        bill.save()
        bill.vendor_invoice_number = "INV-003"
        with self.assertRaises(ValidationError):
            VendorBillApprovalService.save_draft(bill, actor=self.actor)
