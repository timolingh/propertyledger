"""Read-only presentation of the last recorded vendor provisioning result."""
from ledgeros.models import LedgerOSSyncRecord


def vendor_sync_status(vendor):
    record = vendor.sync_record
    status = record.status if record else ''
    labels = {
        '': 'Not synced',
        LedgerOSSyncRecord.Status.PENDING: 'Pending',
        LedgerOSSyncRecord.Status.IN_PROGRESS: 'In progress',
        LedgerOSSyncRecord.Status.SUCCEEDED: 'Synced',
        LedgerOSSyncRecord.Status.FAILED: 'Sync failed',
        LedgerOSSyncRecord.Status.CANCELLED: 'Cancelled',
        LedgerOSSyncRecord.Status.DUPLICATE: 'Needs review',
    }
    guidance = ''
    if status == LedgerOSSyncRecord.Status.FAILED:
        # Upstream errors can contain credentials or response bodies. Render only
        # controlled guidance, never the stored exception or payload.
        error = (record.last_error or '').lower()
        if any(word in error for word in ('401', '403', 'unauthorized', 'forbidden', 'permission')):
            guidance = 'LedgerOS denied access. Ask an administrator to check the connection credentials and vendor permissions, then retry.'
        elif any(word in error for word in ('timeout', 'timed out', 'connection', 'unreachable')):
            guidance = 'LedgerOS could not be reached or did not respond in time. Check the connection and retry this vendor.'
        else:
            guidance = 'LedgerOS provisioning failed. Check vendor details and ask an administrator to review connection settings and the Accounts Payable mapping, then retry.'
    elif status != LedgerOSSyncRecord.Status.SUCCEEDED:
        guidance = 'Vendor sync is not confirmed. Complete LedgerOS connection and Accounts Payable setup, then sync this vendor before posting its bills.'
    return {
        'label': labels.get(status, 'Needs review'),
        'synced': status == LedgerOSSyncRecord.Status.SUCCEEDED,
        'last_synced_at': record.last_synced_at if record else None,
        'guidance': guidance,
        'action_label': 'Retry sync' if record else 'Sync to LedgerOS',
    }
