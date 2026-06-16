from __future__ import annotations

from datetime import date
from decimal import Decimal
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
    Unit,
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

    def test_create_sync_record_endpoint_persists_record(self):
        response = self.client.post(
            reverse("ledgeros-sync-record-create"),
            {
                "local_object_type": "tenant_charge",
                "local_object_id": "1",
                "ledgeros_resource_type": "invoice",
                "ledgeros_resource_id": "inv_1",
                "ledgeros_journal_entry_id": "je_1",
                "source_event_type": "invoice_created",
                "external_id": "ext_1",
                "idempotency_key": "idem_1",
                "request_hash": "hash_1",
                "status": LedgerOSSyncRecord.Status.PENDING,
                "attempt_count": 0,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 1)

    def test_local_health_endpoint_is_healthy(self):
        response = self.client.get(reverse("local-health"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["healthy"])


class LedgerOSSetupViewTests(TestCase):
    def test_setup_view_renders_and_saves_configuration(self):
        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PropertyLedger Setup")
        self.assertContains(response, "Setup Status")
        self.assertContains(response, "Recommended Order")
        self.assertContains(response, "Create owners")

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

    def test_setup_view_uses_friendly_validation_labels(self):
        response = self.client.get(reverse("ledgeros-setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Required account mappings")
        self.assertContains(response, "LedgerOS health")
        self.assertNotContains(response, "required_account_mappings:")
        self.assertNotContains(response, "ledgeros_health:")


class PropertyLedgerDomainModelTests(TestCase):
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
        self.assertEqual(lease.base_monthly_rent_currency, "USD")
        self.assertEqual(lease.deposit_required_currency, "USD")

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

    def test_property_unit_tenant_and_lease_crud_flow(self):
        owner = Owner.objects.create(name="Owner One", is_active=True)

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
                "base_monthly_rent_currency": "USD",
                "deposit_required_amount": "500.00",
                "deposit_required_currency": "USD",
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

        archive_response = self.client.post(reverse("property-archive", args=[property_obj.pk]))
        self.assertEqual(archive_response.status_code, 302)
        property_obj.refresh_from_db()
        self.assertEqual(property_obj.status, Property.Status.ARCHIVED)

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
