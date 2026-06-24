from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord, Owner, Property, Tenant, TenantCharge
from payments.models import PaymentWorkflowSettings, SecurityDepositEvent, TenantPayment
from payments.services import SecurityDepositLedgerService, TenantPaymentService


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


class TenantPaymentServiceTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        self.owner = Owner.objects.create(name="Owner One")
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.tenant = Tenant.objects.create(name="Tenant One")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_allocate_payment_uses_category_priority_and_oldest_charge_first(self, mock_urlopen):
        charge_utility_old = TenantCharge.objects.create(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("30.00"),
            description="Utility old",
        )
        charge_utility_new = TenantCharge.objects.create(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 2),
            due_date=date(2026, 1, 11),
            amount=Decimal("40.00"),
            description="Utility new",
        )
        charge_late_fee = TenantCharge.objects.create(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.LATE_FEE_MANUAL,
            charge_date=date(2026, 1, 3),
            due_date=date(2026, 1, 12),
            amount=Decimal("20.00"),
            description="Late fee",
        )

        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"payment_application": {"id": "ap_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment_application": {"id": "ap_2"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment_application": {"id": "ap_3"}}).encode("utf-8")),
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

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_payment_cannot_sync_until_fully_allocated(self, mock_urlopen):
        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 1, 15),
            amount=Decimal("100.00"),
            payment_method=TenantPayment.PaymentMethod.CASH,
            reference="cash",
            status=TenantPayment.Status.DRAFT,
        )

        with self.assertRaises(ValidationError):
            TenantPaymentService.sync_payment(payment)

        TenantCharge.objects.create(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("60.00"),
            description="Utility",
        )

        mock_urlopen.return_value = _FakeResponse(
            status=201,
            payload=json.dumps({"payment_application": {"id": "ap_1"}}).encode("utf-8"),
        )

        payment = TenantPaymentService.allocate_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, TenantPayment.Status.ALLOCATED)
        self.assertEqual(payment.remaining_amount, Decimal("40.00"))

        with self.assertRaises(ValidationError):
            TenantPaymentService.sync_payment(payment)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_full_payment_sync_creates_payment_and_application_sync_records(self, mock_urlopen):
        charge = TenantCharge.objects.create(
            property=self.property,
            tenant=self.tenant,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 10),
            amount=Decimal("75.00"),
            description="Utility",
        )
        mock_urlopen.side_effect = [
            _FakeResponse(status=201, payload=json.dumps({"payment_application": {"id": "ap_1"}}).encode("utf-8")),
            _FakeResponse(status=201, payload=json.dumps({"payment": {"id": "pay_1"}}).encode("utf-8")),
        ]

        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 1, 15),
            amount=Decimal("75.00"),
            payment_method=TenantPayment.PaymentMethod.CHECK,
            reference="1234",
            status=TenantPayment.Status.DRAFT,
        )

        TenantPaymentService.allocate_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, TenantPayment.Status.READY_TO_SYNC)
        TenantPaymentService.sync_payment(payment)
        payment.refresh_from_db()

        self.assertEqual(payment.status, TenantPayment.Status.SYNCED)
        self.assertIsNotNone(payment.sync_record_id)
        self.assertEqual(payment.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        self.assertEqual(payment.applications.count(), 1)
        self.assertEqual(payment.applications.first().sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        self.assertEqual(mock_urlopen.call_count, 2)


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
