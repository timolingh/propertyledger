from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import Lease, LedgerOSSyncRecord, Owner, Property, Tenant, Unit
from ledgeros.roles import ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.models import SecurityDepositEvent, TenantPayment, TenantPaymentDepositAllocation


class ReceiptDepositVisibilityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('bookkeeper')
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        self.property = Property.objects.create(name='Cedar Grove', primary_owner=Owner.objects.create(name='Owner'))
        self.tenant = Tenant.objects.create(name='Avery Jordan')
        self.lease = Lease.objects.create(unit=Unit.objects.create(property=self.property, name='101'),
            tenant=self.tenant, lease_start_date=date(2026, 6, 1), base_monthly_rent_amount='1450.00',
            deposit_required_amount='1450.00', status='active')
        self.payment = TenantPayment.objects.create(property=self.property, tenant=self.tenant,
            payment_date=date(2026, 11, 6), payment_method='check', amount='1950.00')
        self.allocation = TenantPaymentDepositAllocation.objects.create(payment=self.payment, lease=self.lease, amount='500.00')
        self.event = SecurityDepositEvent.objects.create(property=self.property, unit=self.lease.unit,
            tenant=self.tenant, lease=self.lease, event_type='received', event_date=date(2026, 6, 1), amount='1450.00')

    def confirm(self, obj, journal='journal-1', status='succeeded'):
        record = LedgerOSSyncRecord.objects.create(local_object_type=type(obj).__name__, local_object_id=str(obj.pk),
            source_event_type='test', external_id=f'{type(obj).__name__}-{obj.pk}', idempotency_key=f'{type(obj).__name__}-{obj.pk}',
            request_hash='hash', status=status, ledgeros_journal_entry_id=journal, attempt_count=1)
        obj.sync_record = record
        obj.save()
        return record

    def summary(self):
        response = self.client.get(reverse('security-deposit-list'))
        self.assertEqual(response.status_code, 200)
        return response, response.context['deposit_summary'][0]

    def test_draft_event_is_not_collected_and_receipt_is_visible(self):
        with patch('payments.services.LedgerOSSyncEventService._submit') as upstream:
            response, row = self.summary()
            self.assertEqual(row['required'], Decimal('1450'))
            self.assertEqual(row['received'], 0)
            self.assertEqual(row['remaining'], Decimal('1450'))
            self.assertContains(response, 'Unposted — not counted as received')
            self.assertContains(response, reverse('tenant-payment-detail', args=[self.payment.pk]))
            upstream.assert_not_called()
        self.assertFalse(LedgerOSSyncRecord.objects.exists())

    def test_confirmed_component_counts_before_parent_finalization_and_not_twice(self):
        self.confirm(self.allocation)
        _, row = self.summary()
        self.assertEqual(row['received'], Decimal('500'))
        self.assertEqual(row['remaining'], Decimal('950'))
        self.payment.status = 'posted'
        self.payment.save()
        _, row = self.summary()
        self.assertEqual(row['received'], Decimal('500'))
        self.confirm(self.event, journal='journal-2')
        _, row = self.summary()
        self.assertEqual(row['received'], Decimal('1950'))
        self.assertEqual(row['remaining'], 0)
        self.assertEqual(row['excess'], Decimal('500'))
        self.assertContains(self.client.get(reverse('security-deposit-list')), '$500.00 over requirement')

    def test_uncertain_or_legacy_journalless_success_does_not_claim_balance(self):
        record = self.confirm(self.allocation, journal=None)
        _, row = self.summary()
        self.assertEqual(row['received'], 0)
        self.assertIsNone(row['remaining'])
        record.status = 'failed'
        record.save()
        _, row = self.summary()
        self.assertIsNone(row['remaining'])

    def test_voided_and_other_lease_activity_does_not_count(self):
        self.confirm(self.allocation)
        self.payment.status = 'voided'
        self.payment.save()
        _, row = self.summary()
        self.assertEqual(row['received'], 0)
        self.assertEqual(row['remaining'], Decimal('1450'))

    def test_refund_does_not_silently_create_recollection_obligation(self):
        self.confirm(self.allocation)
        self.event.event_type = 'refunded'
        self.event.save()
        self.confirm(self.event)
        _, row = self.summary()
        self.assertEqual(row['received'], Decimal('500'))
        self.assertIsNone(row['remaining'])

    def test_receipt_action_and_component_explanation(self):
        response = self.client.get(reverse('tenant-payment-detail', args=[self.payment.pk]))
        self.assertContains(response, 'Apply rent and post to LedgerOS')
        self.assertContains(response, 'Post receipt to LedgerOS')
        self.assertContains(response, 'Payment date')
        self.assertContains(response, 'Payment method')
        self.assertContains(response, reverse('security-deposit-list'))
        self.payment.amount = '500.00'
        self.payment.save()
        response = self.client.get(reverse('tenant-payment-list'))
        self.assertContains(response, 'Post receipt to LedgerOS')
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        response = self.client.get(reverse('tenant-payment-list'))
        self.assertNotContains(response, 'Post receipt to LedgerOS')
        with patch('payments.views.TenantPaymentService.sync_payment') as sync:
            response = self.client.post(reverse('tenant-payment-list'), {'action':'sync','payment_id':self.payment.pk})
            self.assertEqual(response.status_code, 403)
            sync.assert_not_called()

    def test_standalone_detail_excludes_its_draft_and_includes_receipt(self):
        self.confirm(self.allocation)
        response = self.client.get(reverse('security-deposit-detail', args=[self.event.pk]))
        self.assertEqual(response.context['deposit_totals']['received'], Decimal('500'))
        self.assertEqual(response.context['deposit_totals']['remaining'], Decimal('950'))
        self.assertContains(response, 'Unposted — not counted as received')
        self.assertNotContains(response, 'Held balance')

    def test_other_lease_receipts_do_not_reduce_avery_requirement(self):
        lease = Lease.objects.create(unit=Unit.objects.create(property=self.property, name='102'),
            tenant=Tenant.objects.create(name='Other tenant'), lease_start_date=date(2026, 6, 1),
            base_monthly_rent_amount='1000.00', deposit_required_amount='1000.00')
        payment = TenantPayment.objects.create(property=self.property, tenant=lease.tenant,
            payment_date=date(2026, 11, 6), amount='1000.00', payment_method='check')
        allocation = TenantPaymentDepositAllocation.objects.create(payment=payment, lease=lease, amount='1000.00')
        self.confirm(allocation)
        _, row = self.summary()
        self.assertEqual(row['received'], 0)
        self.assertEqual(row['remaining'], Decimal('1450'))
