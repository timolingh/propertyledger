"""Present recorded tenant provisioning outcomes without contacting LedgerOS."""
from ledgeros.models import AuditLog


def tenant_sync_statuses(tenants):
    tenants = list(tenants)
    results = {
        tenant.pk: {'label': 'Not confirmed', 'synced': False, 'last_synced_at': None,
                    'guidance': 'No successful customer provisioning is recorded. Review and provision this tenant in LedgerOS.'}
        for tenant in tenants
    }
    by_id = {str(tenant.pk): tenant for tenant in tenants}
    latest = set()
    events = AuditLog.objects.filter(
        record_type='Tenant', record_id__in=by_id,
        action__in=['tenant_created', 'tenant_customer_provisioned', 'tenant_customer_provision_failed'],
    ).order_by('-created_at', '-id')
    for event in events:
        tenant = by_id[event.record_id]
        result = results[tenant.pk]
        success = event.outcome == AuditLog.Outcome.SUCCESS and event.action in {'tenant_created', 'tenant_customer_provisioned'}
        if success and result['last_synced_at'] is None:
            result['last_synced_at'] = event.created_at
        if tenant.pk in latest:
            continue
        latest.add(tenant.pk)
        if success:
            result.update(label='Synced', synced=True, guidance='')
            confirmed_name = event.metadata.get('tenant_name')
            if confirmed_name is not None and confirmed_name != tenant.name.strip():
                result.update(label='Needs review', synced=False,
                              guidance='The tenant name changed after provisioning. Review the LedgerOS customer match before posting invoices.')
        else:
            result.update(label='Sync failed', guidance='Customer provisioning failed. Review the tenant, Accounts Receivable mapping, and LedgerOS connection, then retry from the review page.')
    return results
