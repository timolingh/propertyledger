"""Read-only deposit activity, combining receipt components and standalone events."""
from decimal import Decimal

from django.urls import reverse

from ledgeros.models import Lease, LedgerOSSyncRecord
from payments.models import SecurityDepositEvent, TenantPaymentDepositAllocation


def deposit_activity(*, lease_id=None):
    leases = Lease.objects.select_related('tenant', 'unit__property').order_by('tenant__name', 'id')
    if lease_id is not None:
        leases = leases.filter(pk=lease_id)
    summaries = {
        lease.pk: {'lease': lease, 'required': lease.deposit_required_amount,
                   'received': Decimal('0.00'), 'review': False}
        for lease in leases
    }
    activity = []
    allocations = TenantPaymentDepositAllocation.objects.select_related(
        'payment__tenant', 'lease__unit__property', 'sync_record')
    events = SecurityDepositEvent.objects.select_related('tenant', 'lease__unit__property', 'sync_record')
    if lease_id is not None:
        allocations = allocations.filter(lease_id=lease_id)
        events = events.filter(lease_id=lease_id)
    for obj, is_receipt in [(a, True) for a in allocations] + [(e, False) for e in events]:
        record = obj.sync_record
        voided = (obj.payment.status if is_receipt else obj.status) == 'voided'
        confirmed = bool(not voided and record and record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                         and record.ledgeros_journal_entry_id)
        uncertain = bool(not voided and not confirmed and (
            (record and (record.attempt_count or record.status == LedgerOSSyncRecord.Status.SUCCEEDED))
            or (not is_receipt and obj.status == 'posted')))
        kind = 'received' if is_receipt else obj.event_type
        row = summaries.get(obj.lease_id)
        if row and not voided:
            if confirmed and kind == 'received':
                row['received'] += obj.amount
            # Refunds/deductions do not automatically imply a new collection
            # obligation. Uncertain writes may already exist upstream.
            if uncertain or (confirmed and kind in {'refunded', 'deducted'}):
                row['review'] = True
        activity.append({
            'lease': obj.lease,
            'tenant': obj.payment.tenant if is_receipt else obj.tenant,
            'date': obj.payment.payment_date if is_receipt else obj.event_date,
            'amount': obj.amount,
            'type': 'Deposit received' if is_receipt else obj.get_event_type_display(),
            'source': f'Receipt {obj.payment_id}' if is_receipt else f'Standalone event {obj.pk}',
            'url': reverse('tenant-payment-detail', args=[obj.payment_id]) if is_receipt else reverse('security-deposit-detail', args=[obj.pk]),
            'status': 'Voided' if voided else 'Posted — confirmed' if confirmed else 'Needs review — posting unconfirmed' if uncertain else 'Unposted — not counted as received',
            'journal_id': record.ledgeros_journal_entry_id if confirmed else None,
        })
    for row in summaries.values():
        row['excess'] = max(Decimal('0.00'), row['received'] - row['required'])
        row['remaining'] = None if row['review'] else max(Decimal('0.00'), row['required'] - row['received'])
    return list(summaries.values()), sorted(activity, key=lambda row: (row['date'], row['source']), reverse=True)
