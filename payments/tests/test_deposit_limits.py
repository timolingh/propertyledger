from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from payments.models import SecurityDepositEvent
from payments.services import TenantPaymentService
from payments.tests import test_mixed_receipts as fixtures


class DepositLimitTests(TestCase):
    create_receipt = fixtures.MixedReceiptTests.create_receipt
    create_charge = fixtures.MixedReceiptTests.create_charge
    deposit_response = staticmethod(fixtures.MixedReceiptTests.deposit_response)
    payment_response = staticmethod(fixtures.MixedReceiptTests.payment_response)

    def setUp(self):
        fixtures.MixedReceiptTests.setUp(self)
        self.lease.deposit_required_amount = Decimal('1450.00')
        self.lease.save()

    def event(self, amount='1450.00'):
        return SecurityDepositEvent.objects.create(property=self.property, unit=self.unit,
            tenant=self.tenant, lease=self.lease, event_type='received', event_date=self.lease.lease_start_date,
            amount=Decimal(amount))

    def allocation(self, amount='500.00', total=None):
        receipt = self.create_receipt(total or amount)
        allocation = TenantPaymentService.set_deposit_allocation(payment=receipt, lease=self.lease, amount=Decimal(amount))
        return receipt, allocation

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_standalone_then_receipt_cannot_exceed_requirement(self, upstream):
        from payments.services import SyncResult
        upstream.return_value = SyncResult(201, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})
        event = self.event()
        TenantPaymentService.sync_security_deposit_event(event)
        receipt, allocation = self.allocation()
        with self.assertRaisesMessage(ValidationError, 'exceeds'):
            TenantPaymentService.sync_payment(receipt)
        allocation.refresh_from_db()
        self.assertIsNone(allocation.sync_record_id)
        self.assertEqual(upstream.call_count, 1)

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_receipt_then_standalone_cannot_exceed_requirement(self, upstream):
        from payments.services import SyncResult
        upstream.return_value = SyncResult(201, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})
        receipt, allocation = self.allocation()
        TenantPaymentService.sync_payment(receipt)
        event = self.event()
        with self.assertRaisesMessage(ValidationError, '950.00'):
            TenantPaymentService.sync_security_deposit_event(event)
        event.refresh_from_db()
        self.assertIsNone(event.sync_record_id)
        self.assertIsNone(event.frozen_request_payload)
        self.assertEqual(upstream.call_count, 1)
        event.amount = Decimal('950.00')
        event.save()
        TenantPaymentService.sync_security_deposit_event(event)
        self.assertEqual(upstream.call_count, 2)
        TenantPaymentService.sync_security_deposit_event(event)
        TenantPaymentService.sync_payment(receipt)
        self.assertEqual(upstream.call_count, 2)

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_uncertain_attempt_blocks_other_payment_but_original_retry_survives(self, upstream):
        from payments.services import SyncResult
        upstream.side_effect = [TimeoutError('timeout'), SyncResult(200, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})]
        receipt, allocation = self.allocation()
        TenantPaymentService.sync_payment(receipt)
        allocation.refresh_from_db()
        key = allocation.sync_record.idempotency_key
        event = self.event('100.00')
        with self.assertRaisesMessage(ValidationError, 'unconfirmed'):
            TenantPaymentService.sync_security_deposit_event(event)
        TenantPaymentService.sync_payment(receipt)
        allocation.refresh_from_db()
        self.assertEqual(allocation.sync_record.idempotency_key, key)
        self.assertEqual(upstream.call_count, 2)

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_mixed_receipt_capacity_is_checked_before_any_invoice_post(self, upstream):
        from payments.services import SyncResult
        upstream.return_value = SyncResult(201, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})
        TenantPaymentService.sync_security_deposit_event(self.event())
        charge = self.create_charge('1450.00')
        receipt, allocation = self.allocation(total='1950.00')
        with patch('payments.services.TenantPaymentService.sync_payment_application') as invoice_post:
            with self.assertRaisesMessage(ValidationError, 'exceeds'):
                TenantPaymentService.allocate_payment(receipt)
            invoice_post.assert_not_called()
        self.assertFalse(receipt.applications.exists())

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_local_void_does_not_reopen_posted_deposit_capacity(self, upstream):
        from payments.services import SyncResult
        upstream.return_value = SyncResult(201, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})
        event = self.event()
        TenantPaymentService.sync_security_deposit_event(event)
        event.refresh_from_db()
        event.status = 'voided'
        event.save()
        receipt, allocation = self.allocation()
        with self.assertRaisesMessage(ValidationError, 'exceeds'):
            TenantPaymentService.sync_payment(receipt)
        self.assertEqual(upstream.call_count, 1)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from django.db import close_old_connections
from django.test import TransactionTestCase


class ConcurrentDepositLimitTests(TransactionTestCase):
    setUp = DepositLimitTests.setUp
    event = DepositLimitTests.event
    allocation = DepositLimitTests.allocation
    create_receipt = fixtures.MixedReceiptTests.create_receipt

    @patch('payments.services.LedgerOSSyncEventService._submit')
    def test_receipt_and_standalone_race_share_one_lease_limit(self, upstream):
        from payments.services import SyncResult
        from payments.models import TenantPayment, TenantPaymentDepositAllocation
        def posted(**kwargs):
            sleep(0.1)
            return SyncResult(201, {'sync_event': {'id':'event'}, 'journal_entry': {'id':'journal', 'status':'posted'}})
        upstream.side_effect = posted
        event = self.event()
        receipt, allocation = self.allocation()
        start = Barrier(2)
        def run(kind):
            close_old_connections()
            try:
                start.wait(timeout=10)
                try:
                    if kind == 'receipt':
                        TenantPaymentService.sync_payment(TenantPayment.objects.get(pk=receipt.pk))
                    else:
                        TenantPaymentService.sync_security_deposit_event(SecurityDepositEvent.objects.get(pk=event.pk))
                    return 'posted'
                except ValidationError:
                    return 'blocked'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, kind) for kind in ('receipt', 'event')]
            outcomes = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(outcomes, ['posted', 'blocked'])
        self.assertEqual(upstream.call_count, 1)
        confirmed = sum((obj.amount for obj in list(SecurityDepositEvent.objects.filter(sync_record__status='succeeded'))
                         + list(TenantPaymentDepositAllocation.objects.filter(sync_record__status='succeeded'))), Decimal('0'))
        self.assertLessEqual(confirmed, Decimal('1450'))
