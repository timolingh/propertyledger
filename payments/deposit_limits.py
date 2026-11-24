"""Enforce one lease deposit requirement across every receipt posting path."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from ledgeros.models import Lease, LedgerOSSyncRecord
from payments.models import SecurityDepositEvent, TenantPaymentDepositAllocation


@transaction.atomic
def require_deposit_capacity(*, lease_id, amount, allocation=None, event=None):
    # All callers hold this lock through their posting transaction. Serializing
    # by lease prevents two different source types spending the same capacity.
    lease = Lease.objects.select_for_update().get(pk=lease_id)
    current = allocation if allocation is not None else event
    record = current.sync_record if current is not None else None
    if record and record.attempt_count > 0:
        # Resolve the original operation with its frozen payload/key, even if a
        # timeout or a later lease edit means fresh capacity is no longer enough.
        return

    received = Decimal('0.00')
    allocations = TenantPaymentDepositAllocation.objects.filter(lease_id=lease_id).select_related('sync_record')
    events = SecurityDepositEvent.objects.filter(lease_id=lease_id, event_type='received').select_related('sync_record')
    for source in list(allocations) + list(events):
        if current is not None and type(source) is type(current) and source.pk == current.pk:
            continue
        sync = source.sync_record
        if sync and sync.status == LedgerOSSyncRecord.Status.SUCCEEDED and sync.ledgeros_journal_entry_id:
            received += source.amount
        elif (sync and (sync.attempt_count or sync.status == LedgerOSSyncRecord.Status.SUCCEEDED)) or getattr(source, 'status', '') == 'posted':
            raise ValidationError('This lease has an unconfirmed deposit posting. Reconcile or retry the original record before posting another deposit.')
        # Drafts reserve no funds. Locally voiding a posted source does not
        # reverse its journal, so it must not reopen capacity here.
    if amount <= 0:
        raise ValidationError('A received deposit must be greater than zero.')
    available = max(Decimal('0.00'), lease.deposit_required_amount - received)
    if amount > available:
        raise ValidationError(
            f'Deposit ${amount:,.2f} exceeds the remaining lease requirement of ${available:,.2f}. '
            f'Required: ${lease.deposit_required_amount:,.2f}; already posted: ${received:,.2f}. '
            'Review the receipt split and existing deposit activity before posting.'
        )
