from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from ledgeros.audit import audit_success, audit_failure
from ledgeros.models import Tenant, AuditLog
from ledgeros.roles import ROLE_PROPERTY_MANAGER, ROLE_BOOKKEEPER, assign_user_role
from ledgeros.tenant_sync import tenant_sync_statuses


class TenantSyncStatusTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('manager')
        assign_user_role(self.user, ROLE_PROPERTY_MANAGER)
        self.client.force_login(self.user)
        self.tenant = Tenant.objects.create(name='Dana Morgan', email='dana@example.test')

    @patch('ledgeros.services.LedgerOSCustomerSyncService.create_customer')
    def test_list_reports_evidence_and_links_review_without_syncing(self, create):
        url = reverse('tenant-list')
        self.assertContains(self.client.get(url), 'Not confirmed')
        self.assertContains(self.client.get(url), reverse('tenant-provision', args=[self.tenant.pk]))
        audit_success(action='tenant_customer_provisioned', record=self.tenant, user=self.user,
                      metadata={'tenant_name':'Dana Morgan'})
        self.assertContains(self.client.get(url), 'Synced')
        audit_failure(action='tenant_customer_provision_failed', record_type='Tenant', record_id=str(self.tenant.pk),
                      metadata={'error':'SECRET'})
        response = self.client.get(url)
        self.assertContains(response, 'Sync failed')
        self.assertNotContains(response, 'SECRET')
        status = response.context['rows'][0]['tenant_sync']
        self.assertIsNotNone(status['last_synced_at'])
        self.assertEqual(AuditLog.objects.count(), 2)
        create.assert_not_called()

    def test_creation_success_and_changed_name(self):
        audit_success(action='tenant_created', record=self.tenant, metadata={'tenant_name':'Dana Morgan'})
        self.assertTrue(tenant_sync_statuses([self.tenant])[self.tenant.pk]['synced'])
        self.tenant.name = 'New name'
        self.tenant.save()
        self.assertEqual(tenant_sync_statuses([self.tenant])[self.tenant.pk]['label'], 'Needs review')

    def test_unrelated_history_does_not_claim_sync_and_existing_access_is_preserved(self):
        audit_success(action='tenant_updated', record=self.tenant)
        self.assertEqual(tenant_sync_statuses([self.tenant])[self.tenant.pk]['label'], 'Not confirmed')
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.assertEqual(self.client.get(reverse('tenant-list')).status_code, 403)

    def test_status_lookup_uses_one_query_for_multiple_tenants(self):
        tenants = [self.tenant, Tenant.objects.create(name='Other tenant')]
        with self.assertNumQueries(1):
            statuses = tenant_sync_statuses(tenants)
        self.assertEqual(len(statuses), 2)
