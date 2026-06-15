from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord


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
        self.assertContains(response, "PropertyLedger Epic 1 Setup")

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
