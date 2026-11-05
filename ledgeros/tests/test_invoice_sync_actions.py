from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSSyncRecord, Lease, Owner, Property, Tenant, TenantCharge, Unit
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER, assign_user_role
from ledgeros.tests.test_models_and_api import _configure_ledgeros_invoice_sync


class InvoiceSyncActionTests(TestCase):
    def setUp(self):
        _configure_ledgeros_invoice_sync()
        self.user = get_user_model().objects.create_user('invoice-bookkeeper')
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        property_obj = Property.objects.create(name='Cedar Grove', primary_owner=Owner.objects.create(name='Owner'))
        unit = Unit.objects.create(property=property_obj, name='101')
        tenant = Tenant.objects.create(name='Avery Jordan')
        lease = Lease.objects.create(unit=unit, tenant=tenant, lease_start_date=date(2026, 1, 1), base_monthly_rent_amount=Decimal('1450.00'))
        self.invoice = TenantCharge.objects.create(
            property=property_obj, unit=unit, tenant=tenant, lease=lease,
            charge_type=TenantCharge.ChargeType.BASE_RENT,
            billing_period_start=date(2026, 11, 1), billing_period_end=date(2026, 11, 30),
            charge_date=date(2026, 11, 1), due_date=date(2026, 11, 30), amount=Decimal('1450.00'),
        )
        self.url = reverse('charge-detail', args=[self.invoice.pk])
        self.edit_url = reverse('charge-edit', args=[self.invoice.pk])
        health = patch('ledgeros.views.LedgerOSHealthCheckService.check', return_value=SimpleNamespace(healthy=True, details={}, source='ledgeros'))
        health.start()
        self.addCleanup(health.stop)

    @staticmethod
    def posted_response():
        return (201, {'invoice': {'id': 'inv-1'}, 'journal_entry': {'id': 'je-1'}})

    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_detail_and_edit_offer_explicit_post_action_without_writing(self, submit):
        for url in (self.url, self.edit_url):
            response = self.client.get(url)
            self.assertContains(response, '<h2>LedgerOS Sync</h2>', html=True)
            self.assertContains(response, 'Approve and post to LedgerOS')
            self.assertContains(response, f'<form method="post" action="{self.url}">')
            self.assertNotContains(response, 'Record payment')
        self.assertContains(self.client.get(self.edit_url), 'Save any edits before posting')
        submit.assert_not_called()
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 0)

    @patch('ledgeros.views.LedgerOSWriteReadinessService.require')
    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_explicit_post_uses_saved_invoice_and_reports_confirmed_success(self, submit, customer, ready):
        submit.return_value = self.posted_response()
        response = self.client.post(self.url, {'action': 'sync', 'amount': '9999.00'}, follow=True)
        self.assertContains(response, 'Invoice posted to LedgerOS.')
        self.assertContains(response, 'inv-1')
        self.assertContains(response, 'Record payment')
        self.assertNotContains(response, 'Approve and post to LedgerOS')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, TenantCharge.Status.SYNCED)
        self.assertEqual(self.invoice.amount, Decimal('1450.00'))
        self.assertEqual(self.invoice.sync_record.ledgeros_resource_id, 'inv-1')
        submit.assert_called_once()
        customer.assert_not_called()
        ready.assert_called_once()
        # A repeated button submission must not repost a confirmed invoice.
        self.client.post(self.url, {'action': 'sync'})
        submit.assert_called_once()

    @patch('ledgeros.views.LedgerOSWriteReadinessService.require')
    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_failed_post_shows_error_and_retries_original_sync_identity(self, submit, ready):
        submit.side_effect = RuntimeError('LedgerOS returned HTTP 400: {"customer_code":["Unknown customer."]}')
        response = self.client.post(self.url, {'action': 'sync'}, follow=True)
        self.assertContains(response, 'Invoice sync failed.')
        self.assertContains(response, 'The last invoice sync failed')
        self.assertNotContains(response, 'Invoice posted to LedgerOS.')
        self.assertContains(response, 'Approve and post to LedgerOS')
        self.invoice.refresh_from_db()
        record_id, key = self.invoice.sync_record_id, self.invoice.sync_record.idempotency_key
        submit.side_effect = None
        submit.return_value = self.posted_response()
        response = self.client.post(self.url, {'action': 'sync'}, follow=True)
        self.assertContains(response, 'Invoice posted to LedgerOS.')
        self.assertNotContains(response, 'The last invoice sync failed')
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.sync_record_id, self.invoice.sync_record.idempotency_key), (record_id, key))
        self.assertEqual(self.invoice.sync_record.attempt_count, 2)
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 1)

    @patch('ledgeros.views.LedgerOSWriteReadinessService.require', side_effect=ValidationError('LedgerOS is unavailable.'))
    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_outage_stops_before_sync_attempt(self, submit, ready):
        response = self.client.post(self.url, {'action': 'sync'}, follow=True)
        self.assertContains(response, 'LedgerOS is unavailable.')
        submit.assert_not_called()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, TenantCharge.Status.DRAFT)
        self.assertIsNone(self.invoice.sync_record_id)

    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_non_bookkeepers_cannot_post_and_controls_are_hidden(self, submit):
        for role in (ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER):
            user = get_user_model().objects.create_user(role)
            assign_user_role(user, role)
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'Approve and post to LedgerOS')
            self.assertNotContains(response, 'Edit invoice')
            self.assertEqual(self.client.post(self.url, {'action': 'sync'}).status_code, 403)
        submit.assert_not_called()

    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_csrf_and_voided_invoice_reject_posting(self, submit):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {'action': 'sync'}).status_code, 403)
        self.invoice.status = TenantCharge.Status.VOIDED
        self.invoice.save()
        self.assertNotContains(self.client.get(self.url), 'Approve and post to LedgerOS')
        response = self.client.post(self.url, {'action': 'sync'}, follow=True)
        self.assertContains(response, 'Voided invoices cannot be posted.')
        submit.assert_not_called()

    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge')
    def test_unknown_action_does_not_start_sync(self, submit):
        response = self.client.post(self.url, {'action': 'other'}, follow=True)
        self.assertContains(response, 'Choose a valid invoice action.')
        submit.assert_not_called()
