from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
import json
from io import BytesIO
from urllib.error import HTTPError
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from ledgeros.models import (
    Lease,
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.services import TenantChargeService


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


def _configure_ledgeros_invoice_sync():
    settings_obj = LedgerOSConnectionSettings.load()
    settings_obj.base_url = "http://ledgeros-web:8000"
    settings_obj.client_id = "propertyledger"
    settings_obj.hmac_secret_env_var = "LEDGEROS_HMAC_SECRET"
    settings_obj.save()

    setup = PropertyLedgerSetup.load()
    PropertyLedgerAccountMapping.objects.update_or_create(
        setup=setup,
        mapping_key=PropertyLedgerAccountMapping.MappingKey.RENTAL_INCOME,
        defaults={
            "ledgeros_account_id": "4000",
            "ledgeros_account_name": "Rental income",
            "ledgeros_account_type": "revenue",
        },
    )
    PropertyLedgerAccountMapping.objects.update_or_create(
        setup=setup,
        mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_RECEIVABLE,
        defaults={
            "ledgeros_account_id": "1200",
            "ledgeros_account_name": "Accounts receivable",
            "ledgeros_account_type": "asset",
        },
    )


class LedgerOSSyncRecordModelTests(TestCase):
    def test_uniqueness_constraints_are_enforced(self):
        LedgerOSSyncRecord.objects.create(
            local_object_type="tenant_charge",
            local_object_id="1",
            ledgeros_resource_type="invoice",
            ledgeros_resource_id="inv_1",
            ledgeros_journal_entry_id="je_1",
            source_event_type="invoice_created",
            external_id="ext_1",
            idempotency_key="idem_1",
            request_hash="hash_1",
            status=LedgerOSSyncRecord.Status.PENDING,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LedgerOSSyncRecord.objects.create(
                    local_object_type="tenant_charge",
                    local_object_id="1",
                    ledgeros_resource_type="invoice",
                    source_event_type="invoice_created",
                    external_id="ext_2",
                    idempotency_key="idem_2",
                    request_hash="hash_2",
                    status=LedgerOSSyncRecord.Status.PENDING,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LedgerOSSyncRecord.objects.create(
                    local_object_type="tenant_charge",
                    local_object_id="2",
                    ledgeros_resource_type="invoice",
                    source_event_type="invoice_created",
                    external_id="ext_3",
                    idempotency_key="idem_1",
                    request_hash="hash_3",
                    status=LedgerOSSyncRecord.Status.PENDING,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LedgerOSSyncRecord.objects.create(
                    local_object_type="tenant_charge",
                    local_object_id="3",
                    ledgeros_resource_type="invoice",
                    source_event_type="invoice_created",
                    external_id="ext_1",
                    idempotency_key="idem_3",
                    request_hash="hash_4",
                    status=LedgerOSSyncRecord.Status.PENDING,
                )


class LedgerOSApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_sync_event_endpoint_persists_record(self):
        response = self.client.post(
            reverse("ledgeros-sync-event-create"),
            {
                "source_system": "propertyledger",
                "domain_event_type": "tenant_payment.received",
                "external_id": "tenant-payment:1",
                "source_object_type": "tenant_payment",
                "source_object_id": "1",
                "occurred_at": "2026-01-15T12:00:00Z",
                "payload": {"amount": "100.00", "payment_method": "cash"},
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="idem_1",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 1)
        self.assertEqual(LedgerOSSyncRecord.objects.first().source_event_type, "tenant_payment.received")

    def test_create_sync_event_endpoint_replays_identically(self):
        payload = {
            "source_system": "propertyledger",
            "domain_event_type": "security_deposit.received",
            "external_id": "security-deposit:1",
            "source_object_type": "security_deposit_event",
            "source_object_id": "1",
            "occurred_at": "2026-01-15T12:00:00Z",
            "payload": {"amount": "500.00", "event_type": "received"},
        }

        first = self.client.post(
            reverse("ledgeros-sync-event-create"),
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="idem_2",
        )
        second = self.client.post(
            reverse("ledgeros-sync-event-create"),
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="idem_2",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 1)
        self.assertEqual(LedgerOSSyncRecord.objects.first().source_event_type, "security_deposit.received")

    def test_local_health_endpoint_is_healthy(self):
        response = self.client.get(reverse("local-health"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["healthy"])


class LedgerOSSetupViewTests(TestCase):
    def test_setup_view_renders_and_saves_configuration(self):
        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PropertyLedger Setup")
        self.assertContains(response, "What Must Be Configured")
        self.assertContains(response, "LedgerOS connection saved")
        self.assertContains(response, "Required account mappings configured")
        self.assertContains(response, "Accounts Payable Mapping")
        self.assertContains(response, "Setup Status")
        self.assertContains(response, "Recommended Order")
        self.assertContains(response, "Create owners")
        self.assertContains(response, "Create tenant invoices")

        post_response = self.client.post(
            reverse("ledgeros-setup"),
            {
                "base_url": "http://ledgeros.example",
                "client_id": "propertyledger",
                "hmac_secret_env_var": "TEST_LEDGEROS_HMAC_SECRET",
                "api_key_env_var": "",
                "health_path": "/health/",
                "timeout_seconds": 5,
            },
        )

        self.assertEqual(post_response.status_code, 302)
        settings_obj = LedgerOSConnectionSettings.load()
        self.assertEqual(settings_obj.base_url, "http://ledgeros.example")
        self.assertEqual(settings_obj.client_id, "propertyledger")

    def test_setup_view_saves_accounts_payable_mapping(self):
        post_response = self.client.post(
            reverse("ledgeros-setup"),
            {
                "action": "save-mappings",
                "accounts-payable-mapping-ledgeros_account_id": "2000",
                "accounts-payable-mapping-ledgeros_account_name": "Accounts Payable",
                "accounts-payable-mapping-ledgeros_account_type": "liability",
                "accounts-payable-mapping-is_enabled": "on",
                "accounts-payable-mapping-notes": "Used as the default AP account for vendor provisioning.",
            },
        )

        self.assertEqual(post_response.status_code, 302)
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.get(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE
        )
        self.assertEqual(mapping.ledgeros_account_id, "2000")
        self.assertEqual(mapping.ledgeros_account_name, "Accounts Payable")
        self.assertEqual(mapping.ledgeros_account_type, "liability")
        self.assertTrue(mapping.is_enabled)

    def test_setup_view_uses_friendly_validation_labels(self):
        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Required account mappings")
        self.assertContains(response, "LedgerOS health")
        self.assertContains(response, "Blocking Issues")
        self.assertNotContains(response, "required_account_mappings:")
        self.assertNotContains(response, "ledgeros_health:")

    def test_setup_view_links_record_tenant_payments_to_create_form(self):
        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("invoice-list")}"',
        )


class PropertyLedgerDomainModelTests(TestCase):
    def test_property_plural_name_is_properties(self):
        self.assertEqual(Property._meta.verbose_name_plural, "Properties")

    def test_lease_defaults_rent_effective_date_to_lease_start(self):
        owner = Owner.objects.create(name="Owner One")
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        unit = Unit.objects.create(property=property_obj, name="101")
        tenant = Tenant.objects.create(name="Tenant One")

        lease = Lease.objects.create(
            unit=unit,
            tenant=tenant,
            lease_start_date=date(2026, 1, 1),
            base_monthly_rent_amount=Decimal("1500.00"),
            deposit_required_amount=Decimal("500.00"),
        )

        self.assertEqual(str(lease.rent_effective_date), "2026-01-01")
        self.assertIsNone(lease.lease_end_date)

    def test_tenant_charge_can_be_property_level_manual_charge(self):
        owner = Owner.objects.create(name="Owner One")
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )

        charge = TenantCharge(
            property=property_obj,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 15),
            due_date=date(2026, 1, 31),
            amount=Decimal("125.00"),
            description="Water reimbursement",
        )
        charge.full_clean()
        charge.save()

        self.assertIsNone(charge.lease_id)
        self.assertEqual(charge.get_charge_scope_summary(), "Property One")

    def test_base_rent_charge_infers_scope_from_lease(self):
        owner = Owner.objects.create(name="Owner One")
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        unit = Unit.objects.create(property=property_obj, name="101")
        tenant = Tenant.objects.create(name="Tenant One")
        lease = Lease.objects.create(
            unit=unit,
            tenant=tenant,
            lease_start_date=date(2026, 1, 1),
            base_monthly_rent_amount=Decimal("1500.00"),
            deposit_required_amount=Decimal("500.00"),
        )

        charge = TenantCharge(
            lease=lease,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 31),
            amount=Decimal("1500.00"),
            description="January rent",
        )
        charge.full_clean()
        charge.save()

        self.assertEqual(charge.property, property_obj)
        self.assertEqual(charge.unit, unit)
        self.assertEqual(charge.tenant, tenant)

    def test_rent_generation_is_prorated_for_mid_month_start(self):
        owner = Owner.objects.create(name="Owner One")
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        unit = Unit.objects.create(property=property_obj, name="101")
        tenant = Tenant.objects.create(name="Tenant One")
        Lease.objects.create(
            unit=unit,
            tenant=tenant,
            lease_start_date=date(2026, 1, 16),
            base_monthly_rent_amount=Decimal("3100.00"),
            deposit_required_amount=Decimal("500.00"),
            status=Lease.Status.ACTIVE,
        )

        created = TenantChargeService.generate_base_rent_for_month(date(2026, 1, 1))
        self.assertEqual(len(created), 1)
        charge = created[0]
        self.assertEqual(charge.amount, Decimal("1600.00"))
        self.assertEqual(charge.status, TenantCharge.Status.DRAFT)
        self.assertEqual(TenantCharge.objects.count(), 1)

        duplicate = TenantChargeService.generate_base_rent_for_month(date(2026, 1, 1))
        self.assertEqual(duplicate, [])
        self.assertEqual(TenantCharge.objects.count(), 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.services.urlopen")
    def test_approving_charge_posts_invoice_and_sets_synced_status(self, mock_urlopen):
        _configure_ledgeros_invoice_sync()

        owner = Owner.objects.create(name="Owner One")
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        tenant = Tenant.objects.create(name="Tenant One")

        charge = TenantCharge.objects.create(
            property=property_obj,
            tenant=tenant,
            charge_type=TenantCharge.ChargeType.LATE_FEE_MANUAL,
            charge_date=date(2026, 1, 15),
            due_date=date(2026, 1, 31),
            amount=Decimal("25.00"),
            description="Late fee",
            status=TenantCharge.Status.DRAFT,
        )
        mock_urlopen.return_value = _FakeResponse(
            status=201,
            payload=json.dumps(
                {
                    "invoice": {
                        "id": "inv_1",
                        "invoice_number": "API-INV-0001",
                    },
                    "journal_entry": {"id": "je_1"},
                }
            ).encode("utf-8"),
        )

        TenantChargeService.approve_charge(charge)
        charge.refresh_from_db()

        self.assertEqual(charge.status, TenantCharge.Status.SYNCED)
        self.assertIsNotNone(charge.sync_record_id)
        self.assertEqual(charge.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        self.assertEqual(charge.sync_record.ledgeros_resource_id, "inv_1")
        self.assertEqual(charge.sync_record.ledgeros_journal_entry_id, "je_1")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ledgeros-web:8000/api/v1/invoices/")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["customer_code"], f"tenant-{tenant.pk}")
        self.assertEqual(payload["lines"][0]["account_code"], "4000")

    def test_setup_completion_validation_requires_required_state(self):
        setup = PropertyLedgerSetup.load()
        setup.ledgeros_entity_id = "entity_1"
        setup.ledgeros_entity_name = "Main Entity"
        setup.ledgeros_accounting_period_id = "period_1"
        setup.ledgeros_accounting_period_name = "January 2026"
        setup.last_ledgeros_health_check_healthy = True
        setup.last_setup_smoke_healthy = True
        setup.setup_status = PropertyLedgerSetup.Status.COMPLETE
        setup.save()

        for mapping_key in PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS:
            PropertyLedgerAccountMapping.objects.create(
                setup=setup,
                mapping_key=mapping_key,
                ledgeros_account_id=f"acct_{mapping_key}",
                ledgeros_account_name=mapping_key.replace("_", " ").title(),
                ledgeros_account_type="asset"
                if mapping_key
                in {
                    "operating_bank_account",
                    "undeposited_funds",
                    "accounts_receivable",
                }
                else "liability"
                if mapping_key
                in {
                    "accounts_payable",
                    "tenant_security_deposits_liability",
                }
                else "revenue"
                if mapping_key == "rental_income"
                else "expense"
                if mapping_key == "repairs_and_maintenance_expense"
                else "equity",
            )

        setup.full_clean()

    def test_setup_completion_validation_rejects_missing_mappings(self):
        setup = PropertyLedgerSetup.load()
        setup.ledgeros_entity_id = "entity_1"
        setup.ledgeros_entity_name = "Main Entity"
        setup.ledgeros_accounting_period_id = "period_1"
        setup.ledgeros_accounting_period_name = "January 2026"
        setup.last_ledgeros_health_check_healthy = True
        setup.last_setup_smoke_healthy = True
        setup.setup_status = PropertyLedgerSetup.Status.COMPLETE

        with self.assertRaises(ValidationError):
            setup.full_clean()


class PropertyLedgerCrudViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="admin",
            password="password123",
        )
        self.client.force_login(self.user)

    def _create_rental_income_mapping(self):
        _configure_ledgeros_invoice_sync()

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.views.LedgerOSHealthCheckService.check")
    @patch("ledgeros.services.urlopen")
    def test_property_unit_tenant_and_lease_crud_flow(self, mock_urlopen, mock_health_check):
        owner = Owner.objects.create(name="Owner One", is_active=True)
        self._create_rental_income_mapping()
        mock_health_check.return_value = SimpleNamespace(
            healthy=True,
            source="ledgeros",
            details={"status": "healthy"},
        )
        customer_response = _FakeResponse(
            status=201,
            payload=json.dumps(
                {
                    "customer": {
                        "id": "cus_1",
                        "customer_code": "property-1",
                    }
                }
            ).encode("utf-8"),
        )
        invoice_response = _FakeResponse(
            status=201,
            payload=json.dumps(
                {
                    "invoice": {
                        "id": "inv_2",
                        "invoice_number": "API-INV-0002",
                    },
                    "journal_entry": {"id": "je_2"},
                }
            ).encode("utf-8"),
        )
        mock_urlopen.side_effect = [customer_response, customer_response, invoice_response]

        property_response = self.client.post(
            reverse("property-create"),
            {
                "name": "Property One",
                "primary_owner": owner.pk,
                "status": Property.Status.ACTIVE,
                "notes": "Test property",
            },
        )
        self.assertEqual(property_response.status_code, 302)
        property_obj = Property.objects.get(name="Property One")

        unit_response = self.client.post(
            reverse("unit-create"),
            {
                "property": property_obj.pk,
                "name": "101",
                "status": Unit.Status.ACTIVE,
                "notes": "Test unit",
            },
        )
        self.assertEqual(unit_response.status_code, 302)
        unit = Unit.objects.get(name="101")

        tenant_response = self.client.post(
            reverse("tenant-create"),
            {
                "name": "Tenant One",
                "email": "tenant@example.com",
                "phone": "555-1212",
                "is_active": True,
                "notes": "",
            },
        )
        self.assertEqual(tenant_response.status_code, 302)
        tenant = Tenant.objects.get(name="Tenant One")

        lease_response = self.client.post(
            reverse("lease-create"),
            {
                "unit": unit.pk,
                "tenant": tenant.pk,
                "lease_start_date": "2026-01-01",
                "lease_end_date": "",
                "rent_effective_date": "",
                "base_monthly_rent_amount": "1500.00",
                "deposit_required_amount": "500.00",
                "status": Lease.Status.ACTIVE,
                "notes": "",
            },
        )
        self.assertEqual(lease_response.status_code, 302)
        lease = Lease.objects.get(unit=unit, tenant=tenant)
        self.assertEqual(str(lease.rent_effective_date), "2026-01-01")

        self.assertEqual(self.client.get(reverse("property-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("unit-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("tenant-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("lease-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("charge-list")).status_code, 200)

        charge_response = self.client.post(
            reverse("charge-create"),
            {
                "lease": lease.pk,
                "charge_type": TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
                "billing_period_start": "",
                "billing_period_end": "",
                "charge_date": "2026-01-15",
                "due_date": "2026-01-31",
                "amount": "125.00",
                "description": "Water reimbursement",
                "status": TenantCharge.Status.DRAFT,
            },
        )
        self.assertEqual(charge_response.status_code, 302)
        charge = TenantCharge.objects.get(description="Water reimbursement")
        self.assertEqual(charge.property, property_obj)
        self.assertEqual(charge.unit, unit)
        self.assertEqual(charge.tenant, tenant)

        charge_list_response = self.client.get(reverse("charge-list"))
        self.assertEqual(charge_list_response.status_code, 200)
        self.assertContains(charge_list_response, 'name="selected_charge_ids"')
        self.assertContains(charge_list_response, "Approve selected")
        self.assertContains(charge_list_response, "Archive selected")

        approve_response = self.client.post(
            reverse("charge-list"),
            {
                "bulk_action": "approve",
                "selected_charge_ids": [charge.pk],
            },
        )
        self.assertEqual(approve_response.status_code, 302)
        charge.refresh_from_db()
        self.assertEqual(charge.status, TenantCharge.Status.SYNCED)
        self.assertIsNotNone(charge.sync_record_id)
        self.assertEqual(charge.sync_record.status, LedgerOSSyncRecord.Status.SUCCEEDED)
        self.assertEqual(charge.sync_record.ledgeros_resource_id, "inv_2")

        archive_response = self.client.post(
            reverse("charge-list"),
            {
                "bulk_action": "archive",
                "selected_charge_ids": [charge.pk],
            },
        )
        self.assertEqual(archive_response.status_code, 302)
        charge.refresh_from_db()
        self.assertEqual(charge.status, TenantCharge.Status.VOIDED)
        self.assertEqual(mock_urlopen.call_count, 3)

        property_customer_payload = json.loads(mock_urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        tenant_customer_payload = json.loads(mock_urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        invoice_payload = json.loads(mock_urlopen.call_args_list[2].args[0].data.decode("utf-8"))
        self.assertEqual(property_customer_payload["customer_code"], f"property-{property_obj.pk}")
        self.assertEqual(tenant_customer_payload["customer_code"], f"tenant-{tenant.pk}")
        self.assertEqual(invoice_payload["customer_code"], f"tenant-{tenant.pk}")
        self.assertEqual(property_customer_payload["default_ar_account_code"], "1200")
        self.assertEqual(tenant_customer_payload["default_ar_account_code"], "1200")

        archive_response = self.client.post(reverse("property-archive", args=[property_obj.pk]))
        self.assertEqual(archive_response.status_code, 302)
        property_obj.refresh_from_db()
        self.assertEqual(property_obj.status, Property.Status.ARCHIVED)

    @patch("ledgeros.views.LedgerOSHealthCheckService.check")
    @patch("ledgeros.views.LedgerOSCustomerSyncService.create_customer")
    def test_property_create_rolls_back_when_customer_sync_fails(self, mock_create_customer, mock_health_check):
        owner = Owner.objects.create(name="Owner One", is_active=True)
        self._create_rental_income_mapping()
        mock_health_check.return_value = SimpleNamespace(
            healthy=True,
            source="ledgeros",
            details={"status": "healthy"},
        )
        mock_create_customer.side_effect = ValidationError(
            {"ledgeros": "LedgerOS customer sync failed."}
        )

        response = self.client.post(
            reverse("property-create"),
            {
                "name": "Property One",
                "primary_owner": owner.pk,
                "status": Property.Status.ACTIVE,
                "notes": "Test property",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LedgerOS customer sync failed.")
        self.assertFalse(Property.objects.filter(name="Property One").exists())
        self.assertEqual(mock_create_customer.call_count, 1)

    @patch("ledgeros.views.LedgerOSHealthCheckService.check")
    @patch("ledgeros.views.LedgerOSCustomerSyncService.create_customer")
    def test_tenant_create_rolls_back_when_customer_sync_fails(self, mock_create_customer, mock_health_check):
        self._create_rental_income_mapping()
        mock_health_check.return_value = SimpleNamespace(
            healthy=True,
            source="ledgeros",
            details={"status": "healthy"},
        )
        mock_create_customer.side_effect = ValidationError(
            {"ledgeros": "LedgerOS customer sync failed."}
        )

        response = self.client.post(
            reverse("tenant-create"),
            {
                "name": "Tenant One",
                "email": "tenant@example.com",
                "phone": "555-1212",
                "is_active": True,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LedgerOS customer sync failed.")
        self.assertFalse(Tenant.objects.filter(name="Tenant One").exists())
        self.assertEqual(mock_create_customer.call_count, 1)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.services.urlopen")
    def test_charge_list_shows_sync_error_log(self, mock_urlopen):
        self._create_rental_income_mapping()
        owner = Owner.objects.create(name="Owner One", is_active=True)
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        charge = TenantCharge.objects.create(
            property=property_obj,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 31),
            amount=Decimal("125.00"),
            description="Water reimbursement",
            status=TenantCharge.Status.DRAFT,
        )
        mock_urlopen.return_value = _FakeResponse(
            status=400,
            payload=b'{"error":"Unknown customer"}',
        )

        TenantChargeService.approve_charge(charge)
        charge.refresh_from_db()

        self.assertEqual(charge.status, TenantCharge.Status.SYNC_FAILED)
        response = self.client.get(reverse("charge-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sync log")
        self.assertContains(response, "LedgerOS returned HTTP 400")
        self.assertContains(response, "Unknown customer")

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.services.urlopen")
    def test_http_error_body_is_preserved_in_sync_failure(self, mock_urlopen):
        self._create_rental_income_mapping()
        owner = Owner.objects.create(name="Owner One", is_active=True)
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        charge = TenantCharge.objects.create(
            property=property_obj,
            charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            charge_date=date(2026, 1, 1),
            due_date=date(2026, 1, 31),
            amount=Decimal("125.00"),
            description="Water reimbursement",
            status=TenantCharge.Status.DRAFT,
        )
        mock_urlopen.side_effect = HTTPError(
            url="http://ledgeros-web:8000/api/v1/invoices/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":"Missing or invalid authorization"}'),
        )

        TenantChargeService.approve_charge(charge)
        charge.refresh_from_db()

        self.assertEqual(charge.status, TenantCharge.Status.SYNC_FAILED)
        self.assertIn(
            "LedgerOS returned HTTP 403: {\"error\":\"Missing or invalid authorization\"}",
            charge.sync_record.last_error,
        )
        self.assertEqual(
            charge.sync_record.response_payload,
            {
                "status": "failed",
                "error": (
                    "LedgerOS returned HTTP 403: "
                    '{"error":"Missing or invalid authorization"}'
                ),
            },
        )

    def test_create_pages_explain_required_setup_order(self):
        property_response = self.client.get(reverse("property-create"))
        self.assertEqual(property_response.status_code, 200)
        self.assertContains(
            property_response,
            "Create at least one active owner before adding a property.",
        )
        self.assertContains(property_response, "Go to owners")

        unit_response = self.client.get(reverse("unit-create"))
        self.assertEqual(unit_response.status_code, 200)
        self.assertContains(unit_response, "Create a property before adding units.")
        self.assertContains(unit_response, "Go to properties")

        lease_response = self.client.get(reverse("lease-create"))
        self.assertEqual(lease_response.status_code, 200)
        self.assertContains(
            lease_response, "Create a unit and a tenant before adding a lease."
        )

        charge_response = self.client.get(reverse("charge-create"))
        self.assertEqual(charge_response.status_code, 200)
        self.assertContains(
            charge_response, "Create a property before adding invoices."
        )

    def test_lease_form_uses_date_inputs(self):
        owner = Owner.objects.create(name="Owner One", is_active=True)
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )
        Unit.objects.create(property=property_obj, name="101")
        Tenant.objects.create(name="Tenant One")

        lease_response = self.client.get(reverse("lease-create"))
        self.assertEqual(lease_response.status_code, 200)
        self.assertContains(lease_response, 'type="date"', count=3)

    def test_charge_form_uses_date_inputs(self):
        owner = Owner.objects.create(name="Owner One", is_active=True)
        property_obj = Property.objects.create(
            name="Property One",
            primary_owner=owner,
        )

        response = self.client.get(reverse("charge-create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="date"', count=4)
        self.assertNotContains(response, 'name="property"')
        self.assertNotContains(response, 'name="unit"')
        self.assertNotContains(response, 'name="tenant"')

    def test_admin_lease_add_uses_date_inputs(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="lease-admin",
            password="password123",
            email="admin@example.com",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:ledgeros_lease_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="date"', count=3)
