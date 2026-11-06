from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from ledgeros.models import LedgerOSSyncRecord, Owner, Property
from ledgeros.roles import ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.models import Vendor, VendorBill
from payments.services import VendorService


class VendorSyncUITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('bookkeeper')
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        self.vendor = Vendor.objects.create(name='Landscaper')

    def record(self, status):
        record = LedgerOSSyncRecord.objects.create(
            local_object_type='vendor', local_object_id=str(self.vendor.pk),
            ledgeros_resource_type='vendor', source_event_type='vendor.upsert_requested',
            external_id='vendor-1', idempotency_key='vendor-key', request_hash='hash',
            status=status, last_error='private upstream response SECRET',
            last_synced_at=timezone.now() if status == 'succeeded' else None,
        )
        self.vendor.sync_record = record
        self.vendor.save()
        return record

    @patch('payments.services.LedgerOSVendorSyncService.create_vendor')
    def test_status_reads_do_not_sync_and_never_render_raw_error(self, upstream):
        self.assertContains(self.client.get(reverse('vendor-list')), 'Not synced')
        record = self.record('failed')
        for state, label in [('failed', 'Sync failed'), ('pending', 'Pending'),
                             ('in_progress', 'In progress'), ('succeeded', 'Synced'),
                             ('cancelled', 'Cancelled'), ('duplicate', 'Needs review')]:
            record.status = state
            record.save()
            for url in [reverse('vendor-list'), reverse('vendor-edit', args=[self.vendor.pk])]:
                response = self.client.get(url)
                self.assertContains(response, label)
                self.assertNotContains(response, 'SECRET')
        upstream.assert_not_called()
        self.assertEqual(LedgerOSSyncRecord.objects.count(), 1)

    def test_sync_is_post_only_role_guarded_and_csrf_protected(self):
        url = reverse('vendor-sync', args=[self.vendor.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        with patch.object(VendorService, 'save_and_sync_vendor') as sync:
            self.assertEqual(self.client.post(url).status_code, 403)
            self.assertNotContains(self.client.get(reverse('vendor-list')), 'Sync to LedgerOS</button>')
            sync.assert_not_called()

    @patch('payments.services.VendorService._sync_blockers', return_value=[])
    @patch('payments.services.LedgerOSVendorSyncService._build_vendor_payload', return_value={'code': 'vendor-1'})
    @patch('payments.services.LedgerOSVendorSyncService.create_vendor')
    def test_retry_reuses_identity_and_successful_repeat_does_not_resend(self, upstream, payload, blockers):
        upstream.side_effect = [TimeoutError('SECRET'), SimpleNamespace(payload={'vendor': {'id': 'v1'}})]
        url = reverse('vendor-sync', args=[self.vendor.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.vendor.refresh_from_db()
        record = self.vendor.sync_record
        self.assertEqual(record.status, 'failed')
        key = record.idempotency_key
        self.client.post(url)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.sync_record_id, record.pk)
        self.assertEqual(self.vendor.sync_record.idempotency_key, key)
        self.assertEqual(self.vendor.sync_record.status, 'succeeded')
        self.assertContains(self.client.get(reverse('vendor-edit', args=[self.vendor.pk])), 'Last successful sync')
        self.client.post(url)
        self.assertEqual(upstream.call_count, 2)

    @patch('payments.services.VendorService._sync_blockers', return_value=['Missing AP mapping'])
    @patch('payments.services.LedgerOSVendorSyncService.create_vendor')
    def test_setup_blocked_sync_creates_no_attempt(self, upstream, blockers):
        response = self.client.post(reverse('vendor-sync', args=[self.vendor.pk]), follow=True)
        self.assertContains(response, 'Not synced')
        self.assertContains(response, 'setup')
        self.assertFalse(LedgerOSSyncRecord.objects.exists())
        upstream.assert_not_called()

    def test_bill_explains_vendor_dependency_without_posting(self):
        property_obj = Property.objects.create(name='Building', primary_owner=Owner.objects.create(name='Owner'))
        bill = VendorBill.objects.create(vendor=self.vendor, property=property_obj,
            bill_date=date.today(), due_date=date.today(), amount='315.00', expense_category='other')
        with patch('payments.services.LedgerOSVendorSyncService.create_vendor') as upstream:
            response = self.client.get(reverse('vendor-bill-detail', args=[bill.pk]))
            self.assertContains(response, 'Review vendor and sync')
            self.assertContains(response, 'before an unposted bill can post')
            assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
            response = self.client.get(reverse('vendor-bill-detail', args=[bill.pk]))
            self.assertNotContains(response, 'Review vendor and sync')
            self.assertContains(response, 'Ask a bookkeeper or administrator')
            upstream.assert_not_called()
        self.assertFalse(LedgerOSSyncRecord.objects.exists())
