from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import (
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    Lease,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.roles import ROLE_BOOKKEEPER, assign_user_role
from payments.models import TenantPayment, TenantPaymentDepositAllocation
from payments.services import TenantPaymentService


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 201):
        self.status = status
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _request_payload(call):
    request = call.args[0]
    return request.full_url, json.loads(request.data.decode("utf-8")), request.get_header("Idempotency-key")


class MixedReceiptTests(TestCase):
    def setUp(self):
        settings = LedgerOSConnectionSettings.load()
        settings.base_url = "http://ledgeros-web:8000"
        settings.client_id = "propertyledger"
        settings.hmac_secret_env_var = "LEDGEROS_HMAC_SECRET"
        settings.save()

        setup = PropertyLedgerSetup.load()
        for key, code, name, account_type in (
            (PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT, "1000", "Operating Bank", "asset"),
            (PropertyLedgerAccountMapping.MappingKey.TENANT_SECURITY_DEPOSITS_LIABILITY, "2200", "Tenant Security Deposits", "liability"),
        ):
            PropertyLedgerAccountMapping.objects.create(
                setup=setup,
                mapping_key=key,
                ledgeros_account_id=code,
                ledgeros_account_name=name,
                ledgeros_account_type=account_type,
                is_required=True,
                is_enabled=True,
            )

        owner = Owner.objects.create(name="Owner")
        self.property = Property.objects.create(name="Property", primary_owner=owner)
        self.unit = Unit.objects.create(property=self.property, name="101")
        self.tenant = Tenant.objects.create(name="Tenant")
        self.lease = Lease.objects.create(
            unit=self.unit,
            tenant=self.tenant,
            lease_start_date=date(2026, 1, 1),
            base_monthly_rent_amount=Decimal("1500.00"),
            deposit_required_amount=Decimal("500.00"),
            status=Lease.Status.ACTIVE,
        )

    def create_charge(self, amount="1500.00"):
        charge = TenantCharge.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            charge_date=date(2026, 10, 1),
            due_date=date(2026, 10, 5),
            amount=Decimal(amount),
            description="October rent",
            status=TenantCharge.Status.SYNCED,
        )
        record = LedgerOSSyncRecord.objects.create(
            local_object_type="tenant_charge",
            local_object_id=str(charge.pk),
            ledgeros_resource_type="invoice",
            ledgeros_resource_id=f"invoice-{charge.pk}",
            ledgeros_journal_entry_id=f"invoice-je-{charge.pk}",
            source_event_type="tenant_charge.invoice_created",
            external_id=f"tenant-charge:{charge.pk}",
            idempotency_key=hashlib.sha256(f"charge-{charge.pk}".encode()).hexdigest(),
            request_hash=hashlib.sha256(f"payload-{charge.pk}".encode()).hexdigest(),
            response_payload={"invoice": {"id": f"invoice-{charge.pk}"}},
            status=LedgerOSSyncRecord.Status.SUCCEEDED,
        )
        charge.sync_record = record
        charge.save(update_fields=["sync_record", "updated_at"])
        return charge

    def create_receipt(self, amount="2000.00"):
        return TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 10, 21),
            amount=Decimal(amount),
            payment_method=TenantPayment.PaymentMethod.CHECK,
            reference="MIXED-1",
        )

    def test_bookkeeper_can_save_reviewed_mixed_split_but_cannot_forge_posted_status(self):
        user = get_user_model().objects.create_user(username="mixed-bookkeeper", password="password")
        assign_user_role(user, ROLE_BOOKKEEPER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("tenant-payment-create"),
            {
                "property": self.property.pk,
                "tenant": self.tenant.pk,
                "payment_date": "2026-10-21",
                "amount": "2000.00",
                "payment_method": TenantPayment.PaymentMethod.CHECK,
                "reference": "MIXED-UI-1",
                "notes": "Reviewed at counter",
                "status": TenantPayment.Status.POSTED,
                "deposit_amount": "500.00",
                "deposit_lease": self.lease.pk,
            },
        )

        receipt = TenantPayment.objects.get(reference="MIXED-UI-1")
        self.assertRedirects(response, reverse("tenant-payment-detail", args=[receipt.pk]))
        self.assertEqual(receipt.status, TenantPayment.Status.DRAFT)
        self.assertEqual(receipt.deposit_allocation.amount, Decimal("500.00"))
        self.assertEqual(receipt.rent_amount, Decimal("1500.00"))

    @staticmethod
    def payment_response(payment_id="payment-1", journal_id="payment-je-1", status=201):
        return _FakeResponse(
            {"payment": {"id": payment_id}, "journal_entry": {"id": journal_id, "status": "posted"}},
            status=status,
        )

    @staticmethod
    def deposit_response(status=201):
        return _FakeResponse(
            {"sync_event": {"id": "deposit-event-1"}, "journal_entry": {"id": "deposit-je-1", "status": "posted"}},
            status=status,
        )

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_mixed_receipt_posts_exact_rent_and_deposit_components(self, transport):
        self.create_charge()
        receipt = self.create_receipt()
        TenantPaymentService.set_deposit_allocation(payment=receipt, lease=self.lease, amount=Decimal("500.00"))
        transport.side_effect = [self.payment_response(), self.deposit_response()]

        TenantPaymentService.allocate_payment(receipt)
        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()

        self.assertEqual(receipt.status, TenantPayment.Status.POSTED)
        self.assertEqual(receipt.allocated_amount, Decimal("1500.00"))
        self.assertEqual(receipt.deposit_amount, Decimal("500.00"))
        self.assertEqual(receipt.remaining_amount, Decimal("0.00"))
        self.assertEqual(transport.call_count, 2)
        payment_path, payment_payload, _ = _request_payload(transport.call_args_list[0])
        deposit_path, deposit_payload, _ = _request_payload(transport.call_args_list[1])
        self.assertTrue(payment_path.endswith("/api/v1/payments/"))
        self.assertEqual(payment_payload["amount"], "1500.00")
        self.assertTrue(deposit_path.endswith("/api/v1/sync-events/"))
        self.assertEqual(deposit_payload["occurred_at"], "2026-10-21T00:00:00Z")
        self.assertEqual(
            deposit_payload["payload"]["accounting_entries"],
            [
                {"account_code": "1000", "direction": "debit", "amount": "500.00"},
                {"account_code": "2200", "direction": "credit", "amount": "500.00"},
            ],
        )
        self.assertEqual(receipt.deposit_allocation.sync_record.ledgeros_journal_entry_id, "deposit-je-1")
        self.assertEqual(receipt.sync_record.response_payload["rent_amount"], "1500.00")
        self.assertEqual(receipt.sync_record.response_payload["deposit_amount"], "500.00")
        component_ids = (
            receipt.applications.get().sync_record_id,
            receipt.deposit_allocation.sync_record_id,
            receipt.sync_record_id,
        )
        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(
            (
                receipt.applications.get().sync_record_id,
                receipt.deposit_allocation.sync_record_id,
                receipt.sync_record_id,
            ),
            component_ids,
        )

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_deposit_timeout_retries_frozen_payload_and_key_without_reposting_rent(self, transport):
        self.create_charge()
        receipt = self.create_receipt()
        TenantPaymentService.set_deposit_allocation(payment=receipt, lease=self.lease, amount=Decimal("500.00"))
        transport.side_effect = [self.payment_response(), URLError("timeout"), self.deposit_response(status=200)]

        TenantPaymentService.allocate_payment(receipt)
        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()
        self.assertNotEqual(receipt.status, TenantPayment.Status.POSTED)
        failed_request = transport.call_args_list[1]

        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()
        retry_request = transport.call_args_list[2]
        self.assertEqual(receipt.status, TenantPayment.Status.POSTED)
        self.assertEqual(_request_payload(failed_request)[1:], _request_payload(retry_request)[1:])
        self.assertEqual(receipt.applications.get().sync_record.attempt_count, 1)
        self.assertEqual(receipt.deposit_allocation.sync_record.attempt_count, 2)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_deposit_only_receipt_can_finalize(self, transport):
        receipt = self.create_receipt("500.00")
        TenantPaymentService.set_deposit_allocation(payment=receipt, lease=self.lease, amount=Decimal("500.00"))
        transport.return_value = self.deposit_response()

        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()

        self.assertEqual(receipt.status, TenantPayment.Status.POSTED)
        self.assertFalse(receipt.applications.exists())
        self.assertEqual(transport.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"})
    @patch("payments.services.urlopen")
    def test_deposit_requires_posted_journal_and_locks_economic_edits_after_attempt(self, transport):
        receipt = self.create_receipt("500.00")
        allocation = TenantPaymentService.set_deposit_allocation(
            payment=receipt, lease=self.lease, amount=Decimal("500.00")
        )
        transport.return_value = _FakeResponse({"sync_event": {"id": "audit-only"}})

        TenantPaymentService.sync_payment(receipt)
        allocation.refresh_from_db()
        receipt.refresh_from_db()

        self.assertEqual(allocation.sync_record.status, LedgerOSSyncRecord.Status.FAILED)
        self.assertNotEqual(receipt.status, TenantPayment.Status.POSTED)
        with self.assertRaisesMessage(ValidationError, "cannot be changed"):
            TenantPaymentService.set_deposit_allocation(
                payment=receipt, lease=self.lease, amount=Decimal("400.00")
            )

