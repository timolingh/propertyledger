from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord, Owner, Property, Tenant, TenantCharge, Unit
from ledgeros.models import PropertyLedgerAccountMapping, PropertyLedgerSetup
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.models import DebtServicePayment, MaintenanceCategory, PaymentWorkflowSettings, SecurityDepositEvent, TenantPayment, Vendor, VendorBill, VendorPayment
from payments.services import (
    DebtServicePaymentService,
    MaintenanceExpenseSummaryService,
    SecurityDepositLedgerService,
    TenantPaymentService,
    VendorBillService,
    VendorPaymentService,
    VendorService,
)


class _FakeResponse:
    def __init__(self, *, status: int, payload: bytes):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _configure_ledgeros_settings():
    settings_obj = LedgerOSConnectionSettings.load()
    settings_obj.base_url = "http://ledgeros-web:8000"
    settings_obj.client_id = "propertyledger"
    settings_obj.hmac_secret_env_var = "LEDGEROS_HMAC_SECRET"
    settings_obj.save()


def _configure_epic5_mappings():
    setup = PropertyLedgerSetup.load()
    mapping_defaults = {
        PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT: ("1000", "Operating Bank", "asset"),
        PropertyLedgerAccountMapping.MappingKey.UNDEPOSITED_FUNDS: ("1010", "Undeposited Funds", "asset"),
        PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_RECEIVABLE: ("1100", "Accounts Receivable", "asset"),
        PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE: ("2000", "Accounts Payable", "liability"),
        PropertyLedgerAccountMapping.MappingKey.RENTAL_INCOME: ("4000", "Rental Income", "revenue"),
        PropertyLedgerAccountMapping.MappingKey.REPAIRS_AND_MAINTENANCE_EXPENSE: ("5000", "Operating Expense", "expense"),
        PropertyLedgerAccountMapping.MappingKey.TENANT_SECURITY_DEPOSITS_LIABILITY: ("2200", "Tenant Security Deposits", "liability"),
        PropertyLedgerAccountMapping.MappingKey.OWNER_CONTRIBUTIONS_EQUITY: ("3000", "Owner Contributions Equity", "equity"),
        PropertyLedgerAccountMapping.MappingKey.OWNER_DISTRIBUTIONS_EQUITY: ("3010", "Owner Distributions Equity", "equity"),
        PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY: ("2100", "Credit Card Liability", "liability"),
        PropertyLedgerAccountMapping.MappingKey.MORTGAGE_OR_LOAN_LIABILITY: ("2500", "Mortgage or Loan Payable", "liability"),
        PropertyLedgerAccountMapping.MappingKey.INTEREST_EXPENSE: ("6200", "Interest Expense", "expense"),
        PropertyLedgerAccountMapping.MappingKey.PRINCIPAL_PAYMENT_MAPPING: ("2510", "Principal Payment Mapping", "liability"),
    }
    for mapping_key, (account_id, account_name, account_type) in mapping_defaults.items():
        PropertyLedgerAccountMapping.objects.update_or_create(
            setup=setup,
            mapping_key=mapping_key,
            defaults={
                "ledgeros_account_id": account_id,
                "ledgeros_account_name": account_name,
                "ledgeros_account_type": account_type,
                "is_required": mapping_key in PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS,
                "is_enabled": True,
            },
        )


def _decode_mock_request(mock_call):
    request = mock_call.args[0]
    return request.full_url, json.loads(request.data.decode("utf-8"))


def _create_synced_charge(*, property, tenant, charge_type, charge_date, due_date, amount, description):
    charge = TenantCharge.objects.create(
        property=property,
        tenant=tenant,
        charge_type=charge_type,
        charge_date=charge_date,
        due_date=due_date,
        amount=amount,
        description=description,
        status=TenantCharge.Status.SYNCED,
    )
    request_payload = {
        "local_object_type": "tenant_charge",
        "local_object_id": str(charge.pk),
        "charge_type": charge.charge_type,
        "property_id": charge.property_id,
        "unit_id": charge.unit_id,
        "tenant_id": charge.tenant_id,
        "lease_id": charge.lease_id,
        "billing_period_start": None,
        "billing_period_end": None,
        "amount": str(charge.amount),
        "description": charge.description,
        "due_date": charge.due_date.isoformat(),
    }
    sync_record = LedgerOSSyncRecord.objects.create(
        local_object_type="tenant_charge",
        local_object_id=str(charge.pk),
        ledgeros_resource_type="invoice",
        ledgeros_resource_id=f"inv-{charge.pk}",
        ledgeros_journal_entry_id=f"je-{charge.pk}",
        source_event_type="tenant_charge.invoice_created",
        external_id=f"tenant-charge:{charge.pk}",
        idempotency_key=f"tenant-charge:{charge.pk}:invoice-created",
        request_hash=hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest(),
        response_payload={
            "invoice": {
                "id": f"inv-{charge.pk}",
                "invoice_number": f"tenant-charge:{charge.pk}",
            },
            "journal_entry": {
                "id": f"je-{charge.pk}",
            },
        },
        status=LedgerOSSyncRecord.Status.SUCCEEDED,
    )
    charge.sync_record = sync_record
    charge.save(update_fields=["sync_record", "status", "updated_at"])
    return charge


class PaymentWorkflowSettingsCommandTests(TestCase):
    def test_bootstrap_command_creates_default_allocation_priority(self):
        call_command("bootstrap_payment_workflow_settings")
        settings_obj = PaymentWorkflowSettings.load()
        self.assertEqual(
            settings_obj.charge_type_priority,
            [
                TenantCharge.ChargeType.BASE_RENT,
                TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
                TenantCharge.ChargeType.LATE_FEE_MANUAL,
                TenantCharge.ChargeType.OTHER_MANUAL,
            ],
        )


class PaymentsLandingViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="viewer", password="password")
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        self.client.force_login(self.user)

    def test_landing_page_exposes_record_payment_cta(self):
        response = self.client.get(reverse("payments-home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("invoice-list"))
        self.assertNotContains(response, reverse("banking-dashboard"))
        self.assertContains(response, "Open invoices")


class TenantPaymentViewTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        self.owner = Owner.objects.create(name="Owner One")
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.tenant = Tenant.objects.create(name="Tenant One")
        self.user = get_user_model().objects.create_user(username="tester", password="password")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_allocate_payment_failure_shows_error_message(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("LedgerOS is unavailable")

        _create_synced_charge(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("100.00"),
            description="Base rent",
        )

        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 1, 15),
            amount=Decimal("100.00"),
            payment_method=TenantPayment.PaymentMethod.CASH,
            reference="cash",
            status=TenantPayment.Status.DRAFT,
        )

        response = self.client.post(
            reverse("tenant-payment-detail", args=[payment.pk]),
            {"action": "allocate", "payment_id": payment.pk},
            follow=True,
        )

        payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment allocations refreshed, but one or more posts failed.")
        self.assertContains(response, "LedgerOS is unavailable")
        self.assertContains(response, "Allocation Post Log")
        self.assertEqual(payment.status, TenantPayment.Status.ALLOCATED)
        self.assertIsNone(payment.sync_record)
        self.assertTrue(
            any(
                application.sync_record and application.sync_record.status == LedgerOSSyncRecord.Status.FAILED
                for application in payment.applications.all()
            )
        )

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_sync_payment_failure_shows_error_message(self, mock_urlopen):
        charge = _create_synced_charge(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("100.00"),
            description="Base rent",
        )
        mock_urlopen.side_effect = URLError("LedgerOS is unavailable")

        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 1, 15),
            amount=Decimal("100.00"),
            payment_method=TenantPayment.PaymentMethod.CASH,
            reference="cash",
            status=TenantPayment.Status.DRAFT,
        )
        TenantPaymentService.allocate_payment(payment)
        payment.refresh_from_db()

        response = self.client.post(
            reverse("tenant-payment-detail", args=[payment.pk]),
            {"action": "sync", "payment_id": payment.pk},
            follow=True,
        )

        payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment post to LedgerOS failed.")
        self.assertContains(response, "LedgerOS is unavailable")
        self.assertEqual(payment.status, TenantPayment.Status.READY_TO_SYNC)
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.FAILED)


    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_invoice_receipt_failure_is_visible_and_finalization_retries_payment(self, transport):
        charge = _create_synced_charge(
            property=self.property, tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            charge_date=date(2026, 1, 1), due_date=date(2026, 1, 10),
            amount=Decimal("100.00"), description="Rent",
        )
        transport.side_effect = [
            URLError("LedgerOS is unavailable"),
            _FakeResponse(status=200, payload=json.dumps({
                "payment": {"id": "pay_1"},
                "journal_entry": {"id": "je_1", "status": "posted"},
            }).encode()),
        ]
        response = self.client.post(reverse("invoice-detail", args=[charge.pk]), {
            "payment_date": "2026-01-15", "amount": "100.00", "payment_method": "cash",
        }, follow=True)
        self.assertContains(response, "one or more allocation posts failed")
        payment = TenantPayment.objects.get()
        application_id = payment.applications.get().pk
        response = self.client.post(reverse("tenant-payment-detail", args=[payment.pk]), {
            "action": "sync",
        }, follow=True)
        self.assertContains(response, "Payment posted to LedgerOS.")
        payment.refresh_from_db()
        self.assertEqual(payment.status, TenantPayment.Status.POSTED)
        self.assertEqual(payment.applications.get().pk, application_id)
        self.assertEqual(transport.call_count, 2)
        requests = [call.args[0] for call in transport.call_args_list]
        self.assertTrue(all(request.full_url.endswith("/api/v1/payments/") for request in requests))
        self.assertEqual(requests[0].get_header("Idempotency-key"), requests[1].get_header("Idempotency-key"))


class TenantPaymentServiceTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        self.owner = Owner.objects.create(name="Owner One")
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.tenant = Tenant.objects.create(name="Tenant One")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_allocate_payment_uses_category_priority_and_oldest_charge_first(self, mock_urlopen):
        charge_utility_old = _create_synced_charge(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("30.00"),
            description="Utility old",
        )
        charge_utility_new = _create_synced_charge(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 2),
            due_date=date(2026, 1, 11),
            amount=Decimal("40.00"),
            description="Utility new",
        )
        charge_late_fee = _create_synced_charge(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.LATE_FEE_MANUAL,
            charge_date=date(2026, 1, 3),
            due_date=date(2026, 1, 12),
            amount=Decimal("20.00"),
            description="Late fee",
        )

        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "pay_1"}, "journal_entry": {"id": "je_1", "status": "posted"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "pay_2"}, "journal_entry": {"id": "je_2", "status": "posted"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "pay_3"}, "journal_entry": {"id": "je_3", "status": "posted"}}).encode("utf-8")),
        ]

        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 1, 15),
            amount=Decimal("85.00"),
            payment_method=TenantPayment.PaymentMethod.CASH,
            reference="check 1",
            status=TenantPayment.Status.DRAFT,
        )

        TenantPaymentService.allocate_payment(payment)
        payment.refresh_from_db()

        self.assertEqual(payment.status, TenantPayment.Status.READY_TO_SYNC)
        allocations = list(payment.applications.select_related("charge").order_by("id"))
        self.assertEqual([allocation.charge_id for allocation in allocations], [charge_utility_old.pk, charge_utility_new.pk, charge_late_fee.pk])
        self.assertEqual([allocation.amount_applied for allocation in allocations], [Decimal("30.00"), Decimal("40.00"), Decimal("15.00")])
        self.assertTrue(all(allocation.sync_record and allocation.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED for allocation in allocations))
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertTrue(all(_decode_mock_request(call)[0].endswith("/api/v1/payments/") for call in mock_urlopen.call_args_list))
        first_payload = _decode_mock_request(mock_urlopen.call_args_list[0])[1]
        self.assertEqual(first_payload["source_type"], "invoice")
        self.assertEqual(first_payload["source_reference"], charge_utility_old.sync_record.external_id)
        self.assertEqual(first_payload["amount"], "30.00")
        self.assertEqual(payment.applications.first().sync_record.ledgeros_resource_type, "payment")

    def charge(self, amount="100.00"):
        return _create_synced_charge(
            property=self.property, tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            charge_date=date(2026, 1, 1), due_date=date(2026, 1, 10),
            amount=Decimal(amount), description="Rent",
        )

    def payment(self, amount="100.00"):
        return TenantPayment.objects.create(
            property=self.property, tenant=self.tenant, payment_date=date(2026, 1, 15),
            amount=Decimal(amount), payment_method=TenantPayment.PaymentMethod.CASH,
        )

    def posted_response(self, payment_id="pay_1"):
        return _FakeResponse(status=201, payload=json.dumps({
            "payment": {"id": payment_id},
            "journal_entry": {"id": f"je_{payment_id}", "status": "posted"},
        }).encode())

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_payment_endpoint_permission_error_is_retained(self, transport):
        self.charge()
        payment = self.payment()
        transport.side_effect = HTTPError(
            url="http://ledgeros-web:8000/api/v1/payments/", code=403,
            msg="Forbidden", hdrs=None,
            fp=BytesIO(b'{"detail":"API client is not allowed to perform this action."}'),
        )
        TenantPaymentService.allocate_payment(payment)
        application = payment.applications.get()
        self.assertEqual(application.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
        self.assertIn("POST /api/v1/payments/", application.sync_record.last_error)
        self.assertIn("Check the LedgerOS API client permissions", application.sync_record.last_error)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_finalization_uses_posted_allocations_without_another_request(self, transport):
        charge = self.charge()
        payment = self.payment("60.00")
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        TenantPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, TenantPayment.Status.POSTED)
        self.assertEqual(transport.call_count, 1)
        path, payload = _decode_mock_request(transport.call_args)
        self.assertTrue(path.endswith("/api/v1/payments/"))
        self.assertEqual(payload, {"source_type": "invoice", "source_reference": charge.sync_record.external_id,
                                   "payment_date": "2026-01-15", "amount": "60.00"})
        application = payment.applications.get()
        self.assertEqual(application.sync_record.ledgeros_resource_id, "pay_1")
        self.assertEqual(application.sync_record.ledgeros_journal_entry_id, "je_pay_1")
        self.assertEqual(payment.sync_record.response_payload["applications"][0]["payment_id"], "pay_1")
        from reports.services import PropertyReportService
        report = PropertyReportService.tenant_ledger(
            tenant=self.tenant, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )
        self.assertEqual(dict(report["summary_items"])["Closing balance"], Decimal("40.00"))
        record_id = payment.sync_record_id
        TenantPaymentService.sync_payment(payment)
        self.assertEqual(payment.sync_record_id, record_id)
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_failed_allocation_retries_same_record_and_key_without_reposting_success(self, transport):
        self.charge("40.00")
        self.charge("60.00")
        payment = self.payment()
        replay = self.posted_response("pay_2")
        replay.status = 200  # LedgerOS replays the original committed result.
        transport.side_effect = [self.posted_response(), URLError("timeout"), replay]
        TenantPaymentService.allocate_payment(payment)
        records = list(payment.applications.order_by("id").values_list("id", "sync_record_id"))
        failed_request = transport.call_args_list[-1].args[0]
        TenantPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, TenantPayment.Status.POSTED)
        self.assertEqual(list(payment.applications.order_by("id").values_list("id", "sync_record_id")), records)
        self.assertEqual(transport.call_count, 3)
        retry = transport.call_args.args[0]
        self.assertEqual(retry.get_header("Idempotency-key"), failed_request.get_header("Idempotency-key"))
        self.assertEqual(retry.data, failed_request.data)
        self.assertEqual(len(payment.sync_record.response_payload["applications"]), 2)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_repeated_allocate_preserves_posted_applications(self, transport):
        self.charge()
        payment = self.payment()
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        application_id = payment.applications.get().pk
        TenantPaymentService.allocate_payment(payment)
        self.assertEqual(payment.applications.get().pk, application_id)
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_unapplied_amount_and_voided_payment_cannot_finalize(self, transport):
        self.charge("60.00")
        payment = self.payment()
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        with self.assertRaisesMessage(ValidationError, "fully allocated"):
            TenantPaymentService.sync_payment(payment)
        payment.status = TenantPayment.Status.VOIDED
        payment.save()
        with self.assertRaises(ValidationError):
            TenantPaymentService.sync_payment(payment)
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_audit_only_or_unposted_response_is_not_success(self, transport):
        self.charge()
        for payload in ({"sync_event": {"id": "audit"}},
                        {"payment": {"id": "pay"}, "journal_entry": {"id": "je", "status": "draft"}},
                        {"payment": {"id": "pay"}, "journal_entry": {"status": "posted"}}):
            with self.subTest(payload=payload):
                payment = self.payment()
                transport.return_value = _FakeResponse(status=201, payload=json.dumps(payload).encode())
                TenantPaymentService.allocate_payment(payment)
                application = payment.applications.get()
                self.assertEqual(application.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
                TenantPaymentService.sync_payment(payment)
                payment.refresh_from_db()
                self.assertNotEqual(payment.status, TenantPayment.Status.POSTED)
                self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
                # Free this invoice for the next independent example.
                payment.applications.all().delete()

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_legacy_parent_audit_record_is_preserved(self, transport):
        self.charge()
        payment = self.payment()
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        legacy = LedgerOSSyncRecord.objects.create(
            local_object_type="tenant_payment", local_object_id=str(payment.pk),
            source_event_type="tenant_payment.received", external_id=f"tenant-payment:{payment.pk}",
            idempotency_key="legacy", request_hash="legacy", ledgeros_resource_type="sync_event",
            ledgeros_resource_id="audit_1", status=LedgerOSSyncRecord.Status.FAILED,
            response_payload={"sync_event": {"id": "audit_1"}}, last_error="old failure",
        )
        payment.sync_record = legacy
        payment.save()
        TenantPaymentService.sync_payment(payment)
        payment.refresh_from_db()
        legacy.refresh_from_db()
        self.assertNotEqual(payment.sync_record_id, legacy.pk)
        self.assertEqual(legacy.response_payload, {"sync_event": {"id": "audit_1"}})
        self.assertEqual(legacy.last_error, "old failure")
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_posted_allocation_locks_payment_fields_before_finalization(self, transport):
        from payments.forms import TenantPaymentForm
        self.charge()
        payment = self.payment()
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        form = TenantPaymentForm(instance=payment)
        self.assertTrue(form.fields["amount"].disabled)
        self.assertTrue(form.fields["status"].disabled)
        self.assertFalse(form.fields["notes"].disabled)
        form = TenantPaymentForm(
            data={"amount": "1.00", "status": "draft", "notes": "Receipt reference checked"},
            instance=payment,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.notes, "Receipt reference checked")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_retry_rejects_changed_payload_without_changing_key(self, transport):
        self.charge()
        payment = self.payment()
        transport.side_effect = URLError("timeout")
        TenantPaymentService.allocate_payment(payment)
        application = payment.applications.get()
        original_key = application.sync_record.idempotency_key
        payment.payment_date = date(2026, 1, 16)
        payment.save()
        with self.assertRaisesMessage(ValidationError, "cannot be changed"):
            TenantPaymentService.sync_payment(payment)
        application.sync_record.refresh_from_db()
        self.assertEqual(application.sync_record.idempotency_key, original_key)
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_admin_cannot_edit_posted_allocation_or_payment_amount(self, transport):
        self.charge()
        payment = self.payment()
        transport.return_value = self.posted_response()
        TenantPaymentService.allocate_payment(payment)
        admin = get_user_model().objects.create_superuser("payment-admin", password="password")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:payments_tenantpayment_change", args=[payment.pk]))
        form = response.context["adminform"].form
        self.assertTrue(form.fields["amount"].disabled)
        application = payment.applications.get()
        response = self.client.post(
            reverse("admin:payments_tenantpaymentapplication_change", args=[application.pk]),
            {"amount_applied": "1.00", "charge": application.charge_id, "payment": payment.pk, "_save": "Save"},
        )
        self.assertEqual(response.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.amount_applied, Decimal("100.00"))

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_security_deposit_sync_uses_generic_sync_event_endpoint(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=201,
            payload=json.dumps({"sync_event": {"id": "sync_3"}}).encode("utf-8"),
        )

        unit = Unit.objects.create(property=self.property, name="101")
        lease = unit.leases.create(
            tenant=self.tenant,
            lease_start_date=date(2026, 1, 1),
            base_monthly_rent_amount=Decimal("1000.00"),
            deposit_required_amount=Decimal("500.00"),
            status="active",
        )
        event = SecurityDepositEvent.objects.create(
            property=self.property,
            unit=unit,
            tenant=self.tenant,
            lease=lease,
            event_type=SecurityDepositEvent.EventType.RECEIVED,
            event_date=date(2026, 1, 5),
            amount=Decimal("500.00"),
            description="Deposit received",
        )

        TenantPaymentService.sync_security_deposit_event(event)
        event.refresh_from_db()

        self.assertEqual(event.status, SecurityDepositEvent.Status.POSTED)
        self.assertEqual(event.sync_record.ledgeros_resource_id, "sync_3")
        request_path, payload = _decode_mock_request(mock_urlopen.call_args_list[0])
        self.assertEqual(request_path, "http://ledgeros-web:8000/api/v1/sync-events/")
        self.assertEqual(payload["domain_event_type"], "security_deposit.received")
        self.assertEqual(payload["source_object_type"], "security_deposit_event")
        self.assertEqual(payload["payload"]["lease_id"], lease.pk)


class SecurityDepositLedgerServiceTests(TestCase):
    def setUp(self):
        self.owner = Owner.objects.create(name="Owner One")
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.tenant = Tenant.objects.create(name="Tenant One")
        self.unit = self.property.units.create(name="101")
        self.lease = self.unit.leases.create(
            tenant=self.tenant,
            lease_start_date=date(2026, 1, 1),
            base_monthly_rent_amount=Decimal("1000.00"),
            deposit_required_amount=Decimal("500.00"),
            status="active",
        )

    def test_balance_is_derived_from_event_records(self):
        SecurityDepositEvent.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            event_type=SecurityDepositEvent.EventType.REQUIRED,
            event_date=date(2026, 1, 1),
            amount=Decimal("500.00"),
            description="Required deposit",
        )
        SecurityDepositEvent.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            event_type=SecurityDepositEvent.EventType.RECEIVED,
            event_date=date(2026, 1, 2),
            amount=Decimal("500.00"),
            description="Deposit received",
        )
        SecurityDepositEvent.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            event_type=SecurityDepositEvent.EventType.DEDUCTED,
            event_date=date(2026, 1, 3),
            amount=Decimal("100.00"),
            description="Cleaning deduction",
        )
        SecurityDepositEvent.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            event_type=SecurityDepositEvent.EventType.REFUNDED,
            event_date=date(2026, 1, 4),
            amount=Decimal("50.00"),
            description="Refunded balance",
        )

        self.assertEqual(SecurityDepositLedgerService.required_amount_for_lease(self.lease), Decimal("500.00"))
        self.assertEqual(SecurityDepositLedgerService.balance_for_lease(self.lease), Decimal("350.00"))


class Epic5AccountingServiceTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        _configure_epic5_mappings()
        self.owner = Owner.objects.create(name="Owner One")
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.unit = Unit.objects.create(property=self.property, name="101")
        self.vendor = Vendor.objects.create(name="Vendor One")
        self.lender = Vendor.objects.create(name="Lender One")
        self.category = MaintenanceCategory.objects.create(name="Plumbing")
        users = get_user_model().objects
        self.workflow_admin = users.create_user("workflow-admin")
        self.bill_submitter = users.create_user("bill-submitter")
        self.bill_approver = users.create_user("bill-approver")
        self.bill_payer = users.create_user("bill-payer")
        assign_user_role(self.workflow_admin, ROLE_ADMIN)
        for user in (self.bill_submitter, self.bill_approver, self.bill_payer):
            assign_user_role(user, ROLE_BOOKKEEPER)
        WorkflowAuthorizationService.set_grants(
            target=self.bill_approver, actor=self.workflow_admin,
            can_approve_vendor_bills=True, can_pay_vendor_bills=False,
        )
        WorkflowAuthorizationService.set_grants(
            target=self.bill_payer, actor=self.workflow_admin,
            can_approve_vendor_bills=False, can_pay_vendor_bills=True,
        )
        self.bill_status_patch = patch(
            "payments.services.BillPaymentStatusService.statuses",
            side_effect=lambda bills: {
                bill.pk: {"status": "unpaid", "balance": bill.amount} for bill in bills
            },
        )
        self.bill_status_patch.start()
        self.addCleanup(self.bill_status_patch.stop)

    def _create_vendor_bill(self, **overrides):
        defaults = {
            "vendor": self.vendor,
            "property": self.property,
            "unit": self.unit,
            "bill_date": date(2026, 2, 1),
            "due_date": date(2026, 2, 15),
            "amount": Decimal("125.00"),
            "expense_category": VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            "maintenance_category": self.category,
            "repair_notes": "Leak repair",
            "tenant_chargeable": True,
            "notes": "Initial note",
        }
        defaults.update(overrides)
        return VendorBill.objects.create(**defaults)

    def _approve_bill(self, bill):
        VendorBillApprovalService.submit(bill, actor=self.bill_submitter)
        return VendorBillApprovalService.approve(bill, actor=self.bill_approver)

    def _approve_and_sync_bill(self, bill):
        self._approve_bill(bill)
        return VendorBillService.sync_bill(bill, actor=self.bill_submitter)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_sync_uses_vendor_endpoint_and_updates_sync_record(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=201,
            payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8"),
        )

        VendorService.save_and_sync_vendor(self.vendor)
        self.vendor.refresh_from_db()

        self.assertIsNotNone(self.vendor.sync_record)
        self.assertEqual(self.vendor.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        request_path, payload = _decode_mock_request(mock_urlopen.call_args_list[0])
        self.assertEqual(request_path, "http://ledgeros-web:8000/api/v1/vendors/")
        self.assertEqual(payload["vendor_code"], f"vendor-{self.vendor.pk}")
        self.assertEqual(payload["name"], self.vendor.name)
        self.assertEqual(payload["default_ap_account_code"], "2000")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_update_resyncs_to_ledgeros(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        self.vendor.name = "Vendor One Updated"
        VendorService.save_and_sync_vendor(self.vendor)
        self.vendor.refresh_from_db()

        self.assertEqual(mock_urlopen.call_count, 2)
        first_request_path, first_payload = _decode_mock_request(mock_urlopen.call_args_list[0])
        second_request_path, second_payload = _decode_mock_request(mock_urlopen.call_args_list[1])
        self.assertEqual(first_request_path, "http://ledgeros-web:8000/api/v1/vendors/")
        self.assertEqual(second_request_path, "http://ledgeros-web:8000/api/v1/vendors/")
        self.assertEqual(first_payload["name"], "Vendor One")
        self.assertEqual(second_payload["name"], "Vendor One Updated")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_bill_sync_creates_single_sync_record_and_is_idempotent(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(
                status=201,
                payload=json.dumps({"bill": {"id": "bill_1"}, "journal_entry": {"id": "je_bill_1"}}).encode("utf-8"),
            ),
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(
                status=201,
                payload=json.dumps({"bill": {"id": "bill_1"}, "journal_entry": {"id": "je_bill_1"}}).encode("utf-8"),
            ),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        bill = self._create_vendor_bill()
        self._approve_and_sync_bill(bill)
        bill.refresh_from_db()

        self.assertEqual(bill.status, VendorBill.Status.POSTED)
        self.assertEqual(bill.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        first_request_path, first_payload = _decode_mock_request(mock_urlopen.call_args_list[0])
        second_request_path, second_payload = _decode_mock_request(mock_urlopen.call_args_list[1])
        self.assertEqual(first_request_path, "http://ledgeros-web:8000/api/v1/vendors/")
        self.assertEqual(first_payload["vendor_code"], f"vendor-{bill.vendor.pk}")
        self.assertEqual(first_payload["name"], bill.vendor.name)
        self.assertEqual(first_payload["default_ap_account_code"], "2000")
        self.assertEqual(second_request_path, "http://ledgeros-web:8000/api/v1/bills/")
        self.assertEqual(second_payload["vendor_code"], f"vendor-{bill.vendor.pk}")
        self.assertEqual(second_payload["external_bill_number"], f"vendor-bill:{bill.pk}")
        self.assertEqual(second_payload["lines"][0]["account_code"], "5000")
        self.assertEqual(second_payload["lines"][0]["amount"], "125.00")

        VendorBillService.sync_bill(bill, actor=self.bill_submitter)
        bill.refresh_from_db()
        self.assertEqual(LedgerOSSyncRecord.objects.filter(local_object_type="vendor_bill").count(), 1)
        self.assertEqual(bill.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)

    def test_vendor_bill_sync_requires_synced_vendor(self):
        bill = self._create_vendor_bill()
        self._approve_bill(bill)

        with self.assertRaises(ValidationError) as exc:
            VendorBillService.sync_bill(bill, actor=self.bill_submitter)

        self.assertIn("The vendor must be synced to LedgerOS before this bill can post.", exc.exception.messages)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_payment_credit_card_and_payoff_emit_expected_events(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"bill": {"id": "bill_1"}, "journal_entry": {"id": "je_bill_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "card_payment_1"}, "journal_entry": {"id": "je_payment_1", "status": "posted"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"sync_event": {"id": "sync_payment_2"}, "journal_entry": {"id": "je_payment_2"}}).encode("utf-8")),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        bill = self._create_vendor_bill()
        self._approve_and_sync_bill(bill)

        card_payment = VendorPayment.objects.create(
            vendor=self.vendor,
            vendor_bill=bill,
            payment_date=date(2026, 2, 20),
            amount=Decimal("125.00"),
            payment_method=VendorPayment.PaymentMethod.CREDIT_CARD,
            credit_card_account_name="Card Liability",
            bank_account_name="Operating Bank",
            memo="Card swipe",
            is_credit_card_payoff=False,
        )
        VendorPaymentService.save_and_sync_payment(card_payment, actor=self.bill_payer)
        card_payment.refresh_from_db()

        payoff = VendorPayment.objects.create(
            vendor=self.vendor,
            vendor_bill=bill,
            payment_date=date(2026, 2, 25),
            amount=Decimal("125.00"),
            payment_method=VendorPayment.PaymentMethod.ACH_MANUAL,
            bank_account_name="Operating Bank",
            memo="Payoff",
            is_credit_card_payoff=True,
        )
        VendorPaymentService.save_and_sync_payment(payoff, actor=self.bill_submitter)
        payoff.refresh_from_db()

        self.assertEqual(card_payment.status, VendorPayment.Status.POSTED)
        self.assertEqual(card_payment.sync_record.source_event_type, "vendor_payment.credit_card_settled")
        self.assertEqual(card_payment.sync_record.response_payload["payment"]["id"], "card_payment_1")
        self.assertEqual(card_payment.sync_record.ledgeros_journal_entry_id, "je_payment_1")
        self.assertEqual(card_payment.bank_account_name, "")
        self.assertEqual(payoff.status, VendorPayment.Status.POSTED)
        self.assertEqual(payoff.sync_record.source_event_type, "credit_card.payoff")
        self.assertEqual(payoff.sync_record.response_payload["sync_event"]["id"], "sync_payment_2")
        self.assertEqual(payoff.sync_record.ledgeros_journal_entry_id, "je_payment_2")
        third_request_path, third_payload = _decode_mock_request(mock_urlopen.call_args_list[2])
        fourth_request_path, fourth_payload = _decode_mock_request(mock_urlopen.call_args_list[3])
        self.assertEqual(third_request_path, "http://ledgeros-web:8000/api/v1/payments/")
        self.assertEqual(third_payload["source_type"], "bill")
        self.assertEqual(third_payload["funding_account_code"], "2100")
        self.assertEqual(fourth_request_path, "http://ledgeros-web:8000/api/v1/sync-events/")
        self.assertEqual(fourth_payload["domain_event_type"], "credit_card.payoff")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_payment_sent_uses_payment_endpoint(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"bill": {"id": "bill_1"}, "journal_entry": {"id": "je_bill_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "payment_1"}, "journal_entry": {"id": "je_payment_1", "status": "posted"}}).encode("utf-8")),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        bill = self._create_vendor_bill()
        self._approve_and_sync_bill(bill)

        payment = VendorPayment.objects.create(
            vendor=self.vendor,
            vendor_bill=bill,
            payment_date=date(2026, 2, 20),
            amount=Decimal("125.00"),
            payment_method=VendorPayment.PaymentMethod.ACH_MANUAL,
            bank_account_name="Operating Bank",
            credit_card_account_name="",
            memo="ACH payment",
            is_credit_card_payoff=False,
        )
        VendorPaymentService.save_and_sync_payment(payment, actor=self.bill_payer)
        payment.refresh_from_db()

        self.assertEqual(payment.status, VendorPayment.Status.POSTED)
        self.assertEqual(payment.sync_record.ledgeros_resource_type, "payment")
        request_path, payload = _decode_mock_request(mock_urlopen.call_args_list[2])
        self.assertEqual(request_path, "http://ledgeros-web:8000/api/v1/payments/")
        self.assertEqual(payload["source_type"], "bill")
        self.assertEqual(payload["source_reference"], f"vendor-bill:{bill.pk}")
        self.assertEqual(payload["amount"], "125.00")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_vendor_payment_rejects_undeposited_funds_account(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"bill": {"id": "bill_1"}, "journal_entry": {"id": "je_bill_1"}}).encode("utf-8")),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        bill = self._create_vendor_bill()
        self._approve_and_sync_bill(bill)

        payment = VendorPayment.objects.create(
            vendor=self.vendor,
            vendor_bill=bill,
            payment_date=date(2026, 2, 20),
            amount=Decimal("125.00"),
            payment_method=VendorPayment.PaymentMethod.ACH_MANUAL,
            bank_account_name="Undeposited Funds",
            memo="ACH payment",
            is_credit_card_payoff=False,
        )

        with self.assertRaises(ValidationError) as exc:
            VendorPaymentService.save_and_sync_payment(payment, actor=self.bill_payer)

        self.assertIn("Vendor payments must use the configured operating bank account", str(exc.exception))

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_debt_service_payment_requires_balanced_split_and_posts_sync_event(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=201,
            payload=json.dumps({"sync_event": {"id": "sync_debt_1"}, "journal_entry": {"id": "je_debt_1"}}).encode("utf-8"),
        )

        payment = DebtServicePayment.objects.create(
            property=self.property,
            lender=self.lender,
            payment_date=date(2026, 2, 28),
            total_amount=Decimal("500.00"),
            principal_amount=Decimal("400.00"),
            interest_amount=Decimal("100.00"),
            payment_account_name="Operating Bank",
            loan_liability_account_name="Mortgage Liability",
            interest_expense_account_name="Interest Expense",
            memo="Mortgage payment",
        )
        DebtServicePaymentService.save_and_sync_payment(payment)
        payment.refresh_from_db()

        self.assertEqual(payment.status, DebtServicePayment.Status.POSTED)
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        request_path, payload = _decode_mock_request(mock_urlopen.call_args_list[0])
        self.assertEqual(request_path, "http://ledgeros-web:8000/api/v1/sync-events/")
        self.assertEqual(payload["domain_event_type"], "debt_service.payment_recorded")
        self.assertEqual(payload["payload"]["accounting_entries"][0]["account_code"], "2500")
        self.assertEqual(payload["payload"]["accounting_entries"][1]["account_code"], "6200")
        self.assertEqual(payload["payload"]["accounting_entries"][2]["account_code"], "1000")
        self.assertEqual(payment.sync_record.ledgeros_journal_entry_id, "je_debt_1")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_maintenance_expense_summary_groups_by_category(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"sync_event": {"id": "sync_bill_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"vendor": {"id": "vendor_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"sync_event": {"id": "sync_bill_2"}}).encode("utf-8")),
        ]

        VendorService.save_and_sync_vendor(self.vendor)
        self._approve_and_sync_bill(self._create_vendor_bill(amount=Decimal("50.00")))
        self._approve_and_sync_bill(
            self._create_vendor_bill(
                amount=Decimal("75.00"),
                maintenance_category=None,
                expense_category=VendorBill.ExpenseCategory.OTHER,
            )
        )

        rows = MaintenanceExpenseSummaryService.summary_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["total_amount"] + rows[1]["total_amount"], Decimal("125.00"))
