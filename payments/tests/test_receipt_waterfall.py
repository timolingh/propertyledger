from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase

from ledgeros.roles import ROLE_BOOKKEEPER, ROLE_READ_ONLY_VIEWER, assign_user_role
from payments.tests import test_mixed_receipts as mixed


class ReceiptWaterfallTests(TestCase):
    create_charge = mixed.MixedReceiptTests.create_charge
    create_receipt = mixed.MixedReceiptTests.create_receipt
    payment_response = staticmethod(mixed.MixedReceiptTests.payment_response)
    deposit_response = staticmethod(mixed.MixedReceiptTests.deposit_response)
    # Reuse the established isolated receipt/accounting fixtures.
    def setUp(self):
        mixed.MixedReceiptTests.setUp(self)
        self.user = get_user_model().objects.create_user('waterfall-bookkeeper')
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        from ledgeros.services import HealthCheckResult
        health = patch('ledgeros.services.LedgerOSHealthCheckService.check',
            return_value=HealthCheckResult(healthy=True, source='ledgeros', details={}))
        health.start()
        self.addCleanup(health.stop)

    def save_split(self, receipt, **changes):
        from payments.receipt_services import save_receipt_allocations
        values = dict(invoice_amount=Decimal('1500.00'), deposit_amount=Decimal('500.00'),
                      lease=self.lease, other_amount=Decimal('0.00'), account_code='')
        values.update(changes)
        return save_receipt_allocations(payment=receipt, **values)

    def test_waterfall_includes_late_fees_and_orders_all_invoices_oldest_first(self):
        from payments.receipt_services import receipt_waterfall
        late = self.create_charge('100.00')
        late.charge_type = 'late_fee_manual'
        late.due_date = late.due_date.replace(day=1)
        late.save()
        rent = self.create_charge('1400.00')
        plan = receipt_waterfall(property_id=self.property.pk, tenant_id=self.tenant.pk)
        self.assertEqual([row['id'] for row in plan['invoices']], [late.pk, rent.pk])
        self.assertEqual(plan['invoice_due'], '1500.00')
        receipt = self.create_receipt()
        with patch('payments.services.urlopen') as transport:
            self.save_split(receipt)
        transport.assert_not_called()
        receipt.refresh_from_db()
        self.assertEqual(receipt.unapplied_amount, 0)
        self.assertEqual(list(receipt.applications.values_list('charge_id', 'amount_applied')),
                         [(late.pk, Decimal('100.00')), (rent.pk, Decimal('1400.00'))])

    def test_zero_invoice_and_deposit_allocations_pass_money_to_other(self):
        self.create_charge()
        receipt = self.create_receipt()
        self.save_split(receipt, invoice_amount=Decimal('0.00'), deposit_amount=Decimal('0.00'),
                        other_amount=Decimal('2000.00'), account_code='2300')
        receipt.refresh_from_db()
        self.assertFalse(receipt.applications.exists())
        self.assertEqual(receipt.other_amount, Decimal('2000.00'))
        self.assertEqual(receipt.unapplied_amount, 0)

    def test_invalid_split_rolls_back_without_posting(self):
        self.create_charge()
        receipt = self.create_receipt()
        for changes in ({'other_amount': Decimal('1.00')},
                        {'invoice_amount': Decimal('1600.00')},
                        {'deposit_amount': Decimal('501.00')},
                        {'invoice_amount': Decimal('0.00'), 'deposit_amount': Decimal('0.00'),
                         'other_amount': Decimal('2000.00'), 'account_code': ''},
                        {'invoice_amount': Decimal('0.00'), 'deposit_amount': Decimal('0.00'),
                         'other_amount': Decimal('2000.00'), 'account_code': '2200'}):
            with self.subTest(changes=changes), patch('payments.services.urlopen') as transport:
                with self.assertRaises(ValidationError):
                    self.save_split(receipt, **changes)
                self.assertFalse(receipt.applications.exists())
                transport.assert_not_called()

    def test_receipt_form_saves_reviewed_allocations_without_posting(self):
        self.create_charge()
        with patch('payments.services.urlopen') as transport:
            response = self.client.post(reverse('tenant-payment-create'), {
                'property': self.property.pk, 'tenant': self.tenant.pk,
                'payment_date': '2026-10-21', 'amount': '2100.00', 'payment_method': 'check',
                'reference': 'WATERFALL', 'invoice_amount': '1500.00',
                'deposit_lease': self.lease.pk, 'deposit_amount': '500.00',
                'other_amount': '100.00', 'other_account_code': '2300',
            })
        self.assertEqual(response.status_code, 302)
        transport.assert_not_called()
        from payments.models import TenantPayment
        receipt = TenantPayment.objects.get(reference='WATERFALL')
        self.assertEqual(receipt.unapplied_amount, 0)
        self.assertEqual(receipt.other_allocation.account_code, '2300')
        page = self.client.get(response.url)
        self.assertContains(page, '2300')
        self.assertContains(page, '100.00')

    def test_invoice_entry_opens_same_waterfall_form_and_viewers_cannot_allocate(self):
        charge = self.create_charge()
        page = self.client.get(reverse('invoice-detail', args=[charge.pk]))
        self.assertContains(page, reverse('tenant-payment-create') + '?invoice=')
        assign_user_role(self.user, ROLE_READ_ONLY_VIEWER)
        with patch('payments.services.urlopen') as transport:
            self.assertEqual(self.client.get(reverse('receipt-waterfall-preview')).status_code, 403)
            self.assertEqual(self.client.post(reverse('tenant-payment-create'), {}).status_code, 403)
            transport.assert_not_called()

    @patch('payments.views.LedgerOSWriteReadinessService.require')
    @patch.dict('os.environ', {'LEDGEROS_HMAC_SECRET': 'secret'})
    @patch('payments.services.urlopen')
    def test_three_components_post_once_and_other_is_not_rent(self, transport, readiness):
        self.create_charge()
        receipt = self.create_receipt('2100.00')
        self.save_split(receipt, other_amount=Decimal('100.00'), account_code='2300')
        transport.side_effect = [self.payment_response(), self.deposit_response(), self.deposit_response()]
        url = reverse('tenant-payment-detail', args=[receipt.pk])
        self.client.post(url, {'action': 'sync'})
        self.client.post(url, {'action': 'sync'})
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'posted')
        self.assertEqual(transport.call_count, 3)
        from payments.tests.test_mixed_receipts import _request_payload
        _, payload, _ = _request_payload(transport.call_args)
        entries = payload['payload']['accounting_entries']
        self.assertEqual(entries, [
            {'account_code': '1000', 'direction': 'debit', 'amount': '100.00'},
            {'account_code': '2300', 'direction': 'credit', 'amount': '100.00'},
        ])
        payloads = [_request_payload(call)[1] for call in transport.call_args_list]
        self.assertEqual(Decimal(payloads[0]['amount']), Decimal('1500.00'))
        cash = Decimal(payloads[0]['amount']) + sum(
            (Decimal(row['amount']) for item in payloads[1:] for row in item['payload']['accounting_entries']
             if row['account_code'] == '1000' and row['direction'] == 'debit'), Decimal('0.00'))
        self.assertEqual(cash, Decimal('2100.00'))
        from reports.services import _confirmed_rent_amount
        self.assertEqual(_confirmed_rent_amount(receipt), Decimal('1500.00'))

    @patch('payments.views.LedgerOSWriteReadinessService.require')
    @patch.dict('os.environ', {'LEDGEROS_HMAC_SECRET': 'secret'})
    @patch('payments.services.urlopen')
    def test_other_timeout_reuses_payload_and_key_and_locks_split(self, transport, readiness):
        receipt = self.create_receipt('100.00')
        self.save_split(receipt, invoice_amount=Decimal('0.00'), deposit_amount=Decimal('0.00'),
                        other_amount=Decimal('100.00'), account_code='2300')
        transport.side_effect = [TimeoutError('uncertain'), self.deposit_response()]
        url = reverse('tenant-payment-detail', args=[receipt.pk])
        self.client.post(url, {'action': 'sync'})
        receipt.refresh_from_db()
        self.assertFalse(receipt.is_editable_after_sync)
        with self.assertRaises(ValidationError):
            self.save_split(receipt, invoice_amount=Decimal('0.00'), deposit_amount=Decimal('0.00'),
                            other_amount=Decimal('100.00'), account_code='2400')
        self.client.post(url, {'action': 'sync'})
        from payments.tests.test_mixed_receipts import _request_payload
        self.assertEqual(_request_payload(transport.call_args_list[0]), _request_payload(transport.call_args_list[1]))

    @patch('payments.views.LedgerOSWriteReadinessService.require')
    @patch.dict('os.environ', {'LEDGEROS_HMAC_SECRET': 'secret'})
    @patch('payments.services.urlopen')
    def test_waterfall_can_allocate_existing_money_after_rent_posting(self, transport, readiness):
        from payments.services import TenantPaymentService
        charge = self.create_charge()
        transport.side_effect = [self.payment_response(), self.deposit_response()]
        receipt = TenantPaymentService.record_payment_for_charge(charge=charge, payment_date=charge.charge_date,
            amount=Decimal('2000.00'), payment_method='check')
        original = receipt.applications.get()
        url = reverse('tenant-payment-edit', args=[receipt.pk])
        response = self.client.get(url)
        self.assertTrue(response.context['form'].can_allocate)
        self.assertTrue(response.context['form'].fields['invoice_amount'].disabled)
        response = self.client.post(url, {'invoice_amount': '0.00', 'deposit_lease': self.lease.pk,
            'deposit_amount': '500.00', 'other_amount': '0.00', 'notes': 'Allocate original money', 'action': 'post'})
        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'posted')
        self.assertEqual(receipt.applications.get().pk, original.pk)
        self.assertEqual(receipt.applications.get().sync_record_id, original.sync_record_id)
        self.assertEqual(transport.call_count, 2)

    @patch('payments.views.LedgerOSWriteReadinessService.require')
    @patch.dict('os.environ', {'LEDGEROS_HMAC_SECRET': 'secret'})
    @patch('payments.services.urlopen')
    def test_other_only_receipt_is_separate_in_reports_and_owner_export(self, transport, readiness):
        from payments.services import TenantPaymentService
        from reports.services import _confirmed_rent_amount, PropertyReportService
        receipt = self.create_receipt('100.00')
        self.save_split(receipt, invoice_amount=Decimal('0.00'), deposit_amount=Decimal('0.00'),
                        other_amount=Decimal('100.00'), account_code='2300')
        transport.return_value = self.deposit_response()
        TenantPaymentService.sync_payment(receipt)
        receipt.refresh_from_db()
        self.assertEqual(_confirmed_rent_amount(receipt), 0)
        from datetime import date
        report = PropertyReportService.property_income_expense(property_obj=self.property,
            period_start=date(2026,10,1), period_end=date(2026,10,31))
        section = next(row for row in report['sections'] if row['title'] == 'Other receipt allocations')
        self.assertEqual(section['rows'][0][2:], ['2300', Decimal('100.00')])
        params = {'owner': self.property.primary_owner_id, 'property': self.property.pk,
                  'period_type': 'month', 'period_start': '2026-10-01'}
        export = self.client.get(reverse('owner-statement-export'), params)
        self.assertContains(export, 'Other receipt allocations')
        self.assertContains(export, '2300,100.00')
        self.assertContains(self.client.get(reverse('owner-statement'), params), 'Other receipt allocations')

    def test_stale_invoice_allocation_is_rejected_and_original_draft_is_preserved(self):
        charge = self.create_charge('100.00')
        first, second = self.create_receipt('100.00'), self.create_receipt('100.00')
        self.save_split(first, invoice_amount=Decimal('100.00'), deposit_amount=Decimal('0.00'))
        with self.assertRaises(ValidationError):
            self.save_split(second, invoice_amount=Decimal('100.00'), deposit_amount=Decimal('0.00'))
        self.assertEqual(charge.payment_applications.count(), 1)
        self.assertFalse(second.applications.exists())

    @patch.dict('os.environ', {'LEDGEROS_HMAC_SECRET': 'secret'})
    @patch('payments.services.urlopen')
    def test_form_validated_before_posting_cannot_overwrite_confirmed_receipt(self, transport):
        from payments.receipt_forms import WaterfallReceiptForm
        from payments.receipt_services import save_receipt
        from payments.models import TenantPayment
        from payments.services import TenantPaymentService
        receipt = self.create_receipt('100.00')
        self.save_split(receipt, invoice_amount=Decimal('0.00'), deposit_amount=Decimal('0.00'),
                        other_amount=Decimal('100.00'), account_code='2300')
        form = WaterfallReceiptForm(data={'property': self.property.pk, 'tenant': self.tenant.pk,
            'payment_date': '2026-10-21', 'amount': '200.00', 'payment_method': 'check',
            'invoice_amount': '0.00', 'deposit_amount': '0.00', 'other_amount': '200.00',
            'other_account_code': '2400', 'notes': 'stale edit'}, instance=TenantPayment.objects.get(pk=receipt.pk))
        self.assertTrue(form.is_valid(), form.errors)
        transport.return_value = self.deposit_response()
        posted = TenantPaymentService.sync_payment(TenantPayment.objects.get(pk=receipt.pk))
        saved = save_receipt(form)
        self.assertEqual(saved.status, 'posted')
        self.assertEqual(saved.amount, Decimal('100.00'))
        self.assertEqual(saved.sync_record_id, posted.sync_record_id)
        self.assertEqual(saved.other_allocation.account_code, '2300')
