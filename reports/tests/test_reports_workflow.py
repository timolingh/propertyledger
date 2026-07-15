from __future__ import annotations

import json
import os
import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
from payments.models import MaintenanceCategory, SecurityDepositEvent, TenantPayment, Vendor, VendorBill
from reports.models import OwnerContributionDistribution
from reports.services import OwnerActivityService


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


def _configure_report_mappings():
    setup = PropertyLedgerSetup.load()
    PropertyLedgerAccountMapping.objects.update_or_create(
        setup=setup,
        mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
        defaults={
            "ledgeros_account_id": "1000",
            "ledgeros_account_name": "Operating Bank",
            "ledgeros_account_type": "asset",
        },
    )
    PropertyLedgerAccountMapping.objects.update_or_create(
        setup=setup,
        mapping_key=PropertyLedgerAccountMapping.MappingKey.OWNER_CONTRIBUTIONS_EQUITY,
        defaults={
            "ledgeros_account_id": "3000",
            "ledgeros_account_name": "Owner Contributions",
            "ledgeros_account_type": "equity",
        },
    )
    PropertyLedgerAccountMapping.objects.update_or_create(
        setup=setup,
        mapping_key=PropertyLedgerAccountMapping.MappingKey.OWNER_DISTRIBUTIONS_EQUITY,
        defaults={
            "ledgeros_account_id": "3010",
            "ledgeros_account_name": "Owner Distributions",
            "ledgeros_account_type": "equity",
        },
    )


def _synced_record(*, local_object_type: str, local_object_id: str, source_event_type: str) -> LedgerOSSyncRecord:
    key_suffix = hashlib.sha256(
        f"{local_object_type}:{local_object_id}:{source_event_type}".encode("utf-8")
    ).hexdigest()[:32]
    return LedgerOSSyncRecord.objects.create(
        local_object_type=local_object_type,
        local_object_id=local_object_id,
        ledgeros_resource_type="sync_event",
        ledgeros_resource_id=f"resource-{local_object_id}",
        ledgeros_journal_entry_id=None,
        source_event_type=source_event_type,
        external_id=f"ext-{local_object_id}",
        idempotency_key=f"idem-{key_suffix}",
        request_hash=f"hash-{local_object_id}",
        response_payload={"status": "ok"},
        status=LedgerOSSyncRecord.Status.SUCCEEDED,
    )


class ReportsWorkflowTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        _configure_report_mappings()
        self.user = get_user_model().objects.create_user(username="tester", password="password")
        self.client.force_login(self.user)

        self.owner = Owner.objects.create(name="Owner One", is_active=True)
        self.property = Property.objects.create(name="Property One", primary_owner=self.owner)
        self.unit = Unit.objects.create(property=self.property, name="Unit 1")
        self.tenant = Tenant.objects.create(name="Tenant One", is_active=True)
        self.lease = Lease.objects.create(
            unit=self.unit,
            tenant=self.tenant,
            lease_start_date="2026-05-01",
            base_monthly_rent_amount=Decimal("1000.00"),
            deposit_required_amount=Decimal("500.00"),
            status=Lease.Status.ACTIVE,
        )

    def _create_synced_charge(self, amount: str, charge_type: str = TenantCharge.ChargeType.BASE_RENT) -> TenantCharge:
        charge = TenantCharge.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            charge_type=charge_type,
            billing_period_start=date(2026, 5, 1),
            billing_period_end=date(2026, 5, 31),
            charge_date=date(2026, 5, 1),
            due_date=date(2026, 5, 5),
            amount=Decimal(amount),
            status=TenantCharge.Status.SYNCED,
            description="Test charge",
        )
        charge.sync_record = _synced_record(
            local_object_type="tenant_charge",
            local_object_id=str(charge.pk),
            source_event_type="tenant_charge.invoice_created",
        )
        charge.save(update_fields=["sync_record", "updated_at"])
        return charge

    def _create_synced_payment(self, amount: str) -> TenantPayment:
        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 5, 10),
            amount=Decimal(amount),
            payment_method=TenantPayment.PaymentMethod.CASH,
            status=TenantPayment.Status.POSTED,
        )
        payment.sync_record = _synced_record(
            local_object_type="tenant_payment",
            local_object_id=str(payment.pk),
            source_event_type="tenant_payment.received",
        )
        payment.save(update_fields=["sync_record", "updated_at"])
        return payment

    def _create_synced_bill(self, amount: str, category: str) -> VendorBill:
        vendor = Vendor.objects.create(name="Vendor One", is_active=True)
        bill = VendorBill.objects.create(
            vendor=vendor,
            property=self.property,
            unit=self.unit,
            bill_date=date(2026, 5, 12),
            due_date=date(2026, 5, 20),
            amount=Decimal(amount),
            expense_category=category,
            status=VendorBill.Status.POSTED,
        )
        bill.sync_record = _synced_record(
            local_object_type="vendor_bill",
            local_object_id=str(bill.pk),
            source_event_type="vendor_bill.created",
        )
        bill.save(update_fields=["sync_record", "updated_at"])
        return bill

    def _create_synced_owner_activity(self, amount: str, event_type: str) -> OwnerContributionDistribution:
        activity = OwnerContributionDistribution.objects.create(
            owner=self.owner,
            property=self.property,
            event_type=event_type,
            event_date=date(2026, 5, 15),
            amount=Decimal(amount),
            status=OwnerContributionDistribution.Status.POSTED,
        )
        activity.sync_record = _synced_record(
            local_object_type="owner_contribution_distribution",
            local_object_id=str(activity.pk),
            source_event_type=f"owner_activity.{event_type}",
        )
        activity.save(update_fields=["sync_record", "updated_at"])
        return activity

    def _create_synced_deposit_event(self, amount: str, event_type: str) -> SecurityDepositEvent:
        event = SecurityDepositEvent.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            lease=self.lease,
            event_type=event_type,
            event_date=date(2026, 5, 18),
            amount=Decimal(amount),
            status=SecurityDepositEvent.Status.POSTED,
        )
        event.sync_record = _synced_record(
            local_object_type="security_deposit_event",
            local_object_id=str(event.pk),
            source_event_type=f"security_deposit.{event_type}",
        )
        event.save(update_fields=["sync_record", "updated_at"])
        return event

    def test_owner_statement_preview_reconciles_synced_activity(self):
        self._create_synced_charge("100.00")
        self._create_synced_payment("90.00")
        self._create_synced_bill("25.00", VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE)
        self._create_synced_bill("10.00", VendorBill.ExpenseCategory.MANAGEMENT_FEE)
        self._create_synced_owner_activity("50.00", OwnerContributionDistribution.EventType.CONTRIBUTION)
        self._create_synced_owner_activity("20.00", OwnerContributionDistribution.EventType.DISTRIBUTION)
        self._create_synced_deposit_event("300.00", SecurityDepositEvent.EventType.RECEIVED)

        response = self.client.get(
            reverse("owner-statement"),
            {
                "owner": self.owner.pk,
                "property": self.property.pk,
                "period_type": "month",
                "period_start": "2026-05-15",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner One")
        self.assertContains(response, "Property One")
        self.assertContains(response, "100.00")
        self.assertContains(response, "90.00")
        self.assertContains(response, "25.00")
        self.assertContains(response, "10.00")
        self.assertContains(response, "50.00")
        self.assertContains(response, "20.00")
        self.assertContains(response, "300.00")
        self.assertContains(response, "85.00")

    def test_reports_home_lists_property_and_ledgeros_reports(self):
        response = self.client.get(reverse("reports-home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rent roll")
        self.assertContains(response, "Tenant ledger")
        self.assertContains(response, "Trial balance")
        self.assertContains(response, "Audit drilldown")

    def test_rent_roll_report_lists_active_lease(self):
        response = self.client.get(reverse("rent-roll-report"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Property One")
        self.assertContains(response, "Unit 1")
        self.assertContains(response, "Tenant One")
        self.assertContains(response, "1000.00")

    def test_tenant_ledger_report_shows_running_balance(self):
        self._create_synced_charge("100.00")
        self._create_synced_payment("90.00")

        response = self.client.get(
            reverse("tenant-ledger-report"),
            {
                "property": self.property.pk,
                "tenant": self.tenant.pk,
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Charge")
        self.assertContains(response, "Payment")
        self.assertContains(response, "100.00")
        self.assertContains(response, "90.00")
        self.assertContains(response, "10.00")

    def test_delinquency_report_shows_open_balance(self):
        self._create_synced_charge("100.00")

        response = self.client.get(
            reverse("delinquency-report"),
            {
                "property": self.property.pk,
                "as_of_date": "2026-05-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delinquent charges")
        self.assertContains(response, "100.00")

    def test_property_income_expense_report_summarizes_synced_activity(self):
        self._create_synced_charge("100.00")
        self._create_synced_payment("90.00")
        self._create_synced_bill("25.00", VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE)
        self._create_synced_bill("10.00", VendorBill.ExpenseCategory.MANAGEMENT_FEE)

        response = self.client.get(
            reverse("property-income-expense-report"),
            {
                "property": self.property.pk,
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Income by charge type")
        self.assertContains(response, "Expenses by bill type")
        self.assertContains(response, "Cash collections memo")
        self.assertContains(response, "100.00")
        self.assertContains(response, "25.00")
        self.assertContains(response, "10.00")

    def test_owner_statement_report_page_is_separate_from_epic7_export(self):
        response = self.client.get(
            reverse("owner-statement-report"),
            {
                "owner": self.owner.pk,
                "property": self.property.pk,
                "period_type": "month",
                "period_start": "2026-05-15",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner Statement Report")
        self.assertContains(response, "Open Epic 7 statement")
        self.assertNotContains(response, "Export CSV")

    def test_security_deposit_and_expense_summaries_render(self):
        self._create_synced_deposit_event("300.00", SecurityDepositEvent.EventType.RECEIVED)
        self._create_synced_deposit_event("50.00", SecurityDepositEvent.EventType.DEDUCTED)
        self._create_synced_bill("10.00", VendorBill.ExpenseCategory.MANAGEMENT_FEE)
        self._create_synced_bill("25.00", VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE)

        deposit_response = self.client.get(
            reverse("security-deposit-ledger-report"),
            {
                "property": self.property.pk,
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            },
        )
        management_response = self.client.get(
            reverse("management-fee-expense-summary-report"),
            {
                "property": self.property.pk,
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            },
        )
        maintenance_response = self.client.get(
            reverse("maintenance-expense-summary-report"),
            {
                "property": self.property.pk,
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            },
        )

        self.assertEqual(deposit_response.status_code, 200)
        self.assertContains(deposit_response, "Security deposit events")
        self.assertContains(deposit_response, "300.00")
        self.assertContains(deposit_response, "50.00")
        self.assertEqual(management_response.status_code, 200)
        self.assertContains(management_response, "Management fee expenses")
        self.assertContains(management_response, "10.00")
        self.assertEqual(maintenance_response.status_code, 200)
        self.assertContains(maintenance_response, "Maintenance expenses")
        self.assertContains(maintenance_response, "25.00")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("reports.services.urlopen")
    def test_ledgeros_trial_balance_report_renders_inside_propertyledger(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=200,
            payload=json.dumps(
                [
                    {"account_code": "1000", "account_name": "Operating Bank", "balance": "150.00"},
                    {"account_code": "4000", "account_name": "Rental Income", "balance": "-150.00"},
                ]
            ).encode("utf-8"),
        )

        response = self.client.get(reverse("ledgeros-trial-balance-report"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LedgerOS Trial Balance")
        self.assertContains(response, "Operating Bank")
        self.assertContains(response, "150.00")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertIn("/api/v1/trial-balance/", mock_urlopen.call_args.args[0].full_url)

    def test_pending_sync_report_shows_unsynced_statement_items(self):
        OwnerContributionDistribution.objects.create(
            owner=self.owner,
            property=self.property,
            event_type=OwnerContributionDistribution.EventType.CONTRIBUTION,
            event_date=date(2026, 5, 16),
            amount=Decimal("75.00"),
            status=OwnerContributionDistribution.Status.DRAFT,
        )
        VendorBill.objects.create(
            vendor=Vendor.objects.create(name="Vendor Two", is_active=True),
            property=self.property,
            unit=self.unit,
            bill_date=date(2026, 5, 16),
            due_date=date(2026, 5, 20),
            amount=Decimal("15.00"),
            expense_category=VendorBill.ExpenseCategory.MANAGEMENT_FEE,
            status=VendorBill.Status.DRAFT,
        )

        response = self.client.get(
            reverse("owner-activity-pending-sync"),
            {"owner": self.owner.pk, "property": self.property.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "75.00")
        self.assertContains(response, "15.00")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("reports.services.urlopen")
    def test_owner_activity_sync_posts_to_ledgeros(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=200,
            payload=json.dumps({"sync_event": {"id": "sync-1"}}).encode("utf-8"),
        )
        activity = OwnerContributionDistribution.objects.create(
            owner=self.owner,
            property=self.property,
            event_type=OwnerContributionDistribution.EventType.CONTRIBUTION,
            event_date=date(2026, 5, 16),
            amount=Decimal("25.00"),
        )

        OwnerActivityService.sync_activity(activity)
        activity.refresh_from_db()

        self.assertEqual(activity.status, OwnerContributionDistribution.Status.POSTED)
        self.assertIsNotNone(activity.sync_record)
        self.assertEqual(activity.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        self.assertEqual(activity.sync_record.ledgeros_resource_id, "sync-1")
        self.assertEqual(mock_urlopen.call_count, 1)
