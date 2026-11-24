import json
import os
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from ledgeros.models import AuditLog, LedgerOSConnectionSettings, LedgerOSSyncRecord, Owner, Property, PropertyLedgerAccountMapping, PropertyLedgerSetup, Tenant, TenantCharge
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER, ROLE_READ_ONLY_VIEWER, assign_user_role
from ledgeros.services import LedgerOSCustomerSyncService, TenantChargeService
from ledgeros.tests.test_models_and_api import _FakeResponse, _configure_ledgeros_invoice_sync


class TenantProvisioningTests(TestCase):
    def setUp(self):
        _configure_ledgeros_invoice_sync()
        self.admin = get_user_model().objects.create_user('provision-admin')
        assign_user_role(self.admin, ROLE_ADMIN)
        self.tenant = Tenant.objects.create(name='Avery Jordan')
        self.client.force_login(self.admin)
        self.url = reverse('tenant-provision', args=[self.tenant.pk])
        self.health = patch('ledgeros.views.LedgerOSHealthCheckService.check', return_value=SimpleNamespace(healthy=True, details={}, source='ledgeros'))
        self.health.start()
        self.addCleanup(self.health.stop)

    def review(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context['review_token']

    def confirmation(self):
        return {'customer': {'id': 10, 'customer_code': f'tenant-{self.tenant.pk}',
                             'name': self.tenant.name, 'default_ar_account_code': '1200', 'status': 'active'}}

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_review_is_read_only_and_shows_actual_values(self, create):
        before = LedgerOSSyncRecord.objects.count()
        response = self.client.get(self.url)
        self.assertContains(response, 'Avery Jordan')
        self.assertContains(response, f'tenant-{self.tenant.pk}')
        self.assertContains(response, '1200')
        self.assertContains(response, 'Conflicting customers will not be changed')
        create.assert_not_called()
        self.assertEqual(LedgerOSSyncRecord.objects.count(), before)
        self.assertContains(self.client.get(reverse('tenant-detail', args=[self.tenant.pk])), self.url)

    @patch('ledgeros.services.LedgerOSWriteReadinessService.require')
    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_explicit_submit_confirms_and_audits_without_changing_charges(self, create, ready):
        create.return_value = (201, self.confirmation())
        before = LedgerOSSyncRecord.objects.count()
        response = self.client.post(self.url, {'action': 'provision', 'review_token': self.review()}, follow=True)
        self.assertContains(response, 'Tenant customer provisioned in LedgerOS.')
        create.assert_called_once_with(customer_code=f'tenant-{self.tenant.pk}', name='Avery Jordan', provision_only=True, default_ar_account_code='1200')
        ready.assert_called_once()
        self.assertEqual(LedgerOSSyncRecord.objects.count(), before)
        self.assertEqual(TenantCharge.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(action='tenant_customer_provisioned', actor=self.admin, record_id=str(self.tenant.pk)).exists())

    @patch('ledgeros.services.LedgerOSWriteReadinessService.require')
    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_conflict_failure_and_invalid_confirmation_never_report_success(self, create, ready):
        for result in (RuntimeError('Existing customer conflicts. No customer changes were made.'),
                       (200, {'customer': {'id': 10}})):
            with self.subTest(result=result):
                create.side_effect = result if isinstance(result, Exception) else None
                create.return_value = result
                response = self.client.post(self.url, {'action': 'provision', 'review_token': self.review()})
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Tenant customer provisioned in LedgerOS.')
        self.assertFalse(AuditLog.objects.filter(action='tenant_customer_provisioned').exists())

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_invalid_or_stale_review_does_not_write(self, create):
        token = self.review()
        self.tenant.name = 'Changed after review'
        self.tenant.save()
        response = self.client.post(self.url, {'action': 'provision', 'review_token': token})
        self.assertContains(response, 'Review the current tenant and AR account before provisioning.')
        self.client.post(self.url, {'action': 'provision', 'review_token': 'tampered'})
        create.assert_not_called()

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_changed_ar_mapping_requires_fresh_review(self, create):
        token = self.review()
        PropertyLedgerAccountMapping.objects.filter(mapping_key='accounts_receivable').update(ledgeros_account_id='1300')
        response = self.client.post(self.url, {'action': 'provision', 'review_token': token})
        self.assertContains(response, 'Review the current tenant and AR account before provisioning.')
        create.assert_not_called()

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_missing_setup_review_does_not_bootstrap_or_provision(self, create):
        PropertyLedgerSetup.objects.all().delete()
        LedgerOSConnectionSettings.objects.all().delete()
        response = self.client.get(self.url)
        self.assertContains(response, 'Configure the accounts-receivable mapping')
        self.assertFalse(PropertyLedgerSetup.objects.exists())
        self.assertFalse(LedgerOSConnectionSettings.objects.exists())
        create.assert_not_called()

    @patch('ledgeros.services.LedgerOSWriteReadinessService.require', side_effect=ValidationError('LedgerOS is unavailable.'))
    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_outage_stops_before_customer_request(self, create, ready):
        response = self.client.post(self.url, {'action': 'provision', 'review_token': self.review()})
        self.assertContains(response, 'LedgerOS is unavailable.')
        create.assert_not_called()

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_roles_and_csrf_enforce_explicit_authority(self, create):
        for role in (ROLE_PROPERTY_MANAGER, ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER):
            user = get_user_model().objects.create_user(role)
            assign_user_role(user, role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 200 if role == ROLE_PROPERTY_MANAGER else 403)
            self.assertEqual(self.client.post(self.url, {}).status_code, 200 if role == ROLE_PROPERTY_MANAGER else 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, {'action': 'provision'}).status_code, 403)
        create.assert_not_called()
        with self.assertRaises(PermissionDenied):
            LedgerOSCustomerSyncService.provision_tenant(tenant=self.tenant, actor=user, reviewed_payload={})

    @patch.dict(os.environ, {'LEDGEROS_HMAC_SECRET': 'secret'}, clear=False)
    @patch('ledgeros.services.urlopen')
    def test_strict_adapter_uses_separate_endpoint_and_stable_key(self, transport):
        transport.return_value = _FakeResponse(status=201, payload=json.dumps(self.confirmation()).encode())
        for _ in range(2):
            LedgerOSCustomerSyncService.create_customer(customer_code=f'tenant-{self.tenant.pk}', name=self.tenant.name, provision_only=True)
        first, second = [call.args[0] for call in transport.call_args_list]
        self.assertTrue(first.full_url.endswith('/api/v1/customers/provision/'))
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.get_header('Idempotency-key'), second.get_header('Idempotency-key'))

    @patch.dict(os.environ, {'LEDGEROS_HMAC_SECRET': 'secret'}, clear=False)
    @patch('ledgeros.services.urlopen')
    def test_missing_strict_endpoint_has_no_upsert_fallback(self, transport):
        transport.side_effect = HTTPError('http://ledgeros-web/api/v1/customers/provision/', 404, 'Not found', None, BytesIO(b'Not found'))
        with self.assertRaisesRegex(RuntimeError, 'Update LedgerOS before retrying'):
            LedgerOSCustomerSyncService.create_customer(customer_code=f'tenant-{self.tenant.pk}', name=self.tenant.name, provision_only=True)
        transport.assert_called_once()
        self.assertTrue(transport.call_args.args[0].full_url.endswith('/api/v1/customers/provision/'))

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_editing_tenant_does_not_provision_customer(self, create):
        response = self.client.post(reverse('tenant-edit', args=[self.tenant.pk]), {'name': 'Updated', 'is_active': True, 'email': '', 'phone': '', 'notes': ''})
        self.assertEqual(response.status_code, 302)
        create.assert_not_called()

    @patch('ledgeros.services.LedgerOSInvoiceSyncService.submit_tenant_charge', side_effect=RuntimeError('LedgerOS returned HTTP 400: {"customer_code":["Unknown customer."]}'))
    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_invoice_failure_links_to_explicit_recovery_without_provisioning(self, create, submit):
        property_obj = Property.objects.create(name='Cedar Grove', primary_owner=Owner.objects.create(name='Owner'))
        charge = TenantCharge.objects.create(property=property_obj, tenant=self.tenant, charge_type=TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
                                            charge_date=date(2026, 11, 1), due_date=date(2026, 11, 30), amount=Decimal('25.00'))
        TenantChargeService.approve_charge(charge)
        create.assert_not_called()
        original_id, original_key = charge.sync_record_id, charge.sync_record.idempotency_key
        for url in (reverse('charge-list'), reverse('charge-detail', args=[charge.pk]), reverse('charge-edit', args=[charge.pk])):
            self.assertContains(self.client.get(url), self.url)
        user = get_user_model().objects.create_user('recover-bookkeeper')
        assign_user_role(user, ROLE_BOOKKEEPER)
        self.client.force_login(user)
        response = self.client.get(reverse('charge-list'))
        self.assertNotContains(response, self.url)
        self.assertContains(response, 'Ask an administrator or property manager')
        charge.refresh_from_db()
        self.assertEqual((charge.sync_record_id, charge.sync_record.idempotency_key), (original_id, original_key))

        # Provisioning must not turn an old invoice failure into a claim about
        # the customer's current state, or retry the invoice automatically.
        self.client.force_login(self.admin)
        create.return_value = (201, self.confirmation())
        with patch('ledgeros.services.LedgerOSWriteReadinessService.require'):
            self.client.post(self.url, {'action': 'provision', 'review_token': self.review()})
        create.assert_called_once()
        create.reset_mock()
        submit.assert_called_once()
        for url in (reverse('charge-list'), reverse('charge-detail', args=[charge.pk]), reverse('charge-edit', args=[charge.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'The last invoice sync failed')
            self.assertContains(response, 'If the customer has since been provisioned, retry this invoice.')
            self.assertNotContains(response, 'LedgerOS has no customer for Avery Jordan.')
            if url == reverse('charge-list'):
                self.assertContains(response, 'Review invoice and post')
            else:
                self.assertContains(response, 'Approve and post to LedgerOS')
        create.assert_not_called()
        charge.refresh_from_db()
        self.assertEqual(charge.status, TenantCharge.Status.SYNC_FAILED)
        self.assertEqual((charge.sync_record_id, charge.sync_record.idempotency_key), (original_id, original_key))

        # An explicit successful retry removes recovery guidance without
        # provisioning again or replacing the invoice's sync identity.
        submit.side_effect = None
        submit.return_value = (201, {'invoice': {'id': 'inv-1'}, 'journal_entry': {'id': 'je-1'}})
        TenantChargeService.approve_charge(charge)
        charge.refresh_from_db()
        self.assertEqual(charge.status, TenantCharge.Status.SYNCED)
        self.assertEqual((charge.sync_record_id, charge.sync_record.idempotency_key), (original_id, original_key))
        self.assertNotContains(self.client.get(reverse('charge-detail', args=[charge.pk])), 'The last invoice sync failed')
        create.assert_not_called()
