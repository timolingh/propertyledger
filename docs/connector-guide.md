# PropertyLedger Connector Guide

This guide is for sophisticated users and AI agents building clients around the PropertyLedger public API.

## What this guide covers

- how to talk to PropertyLedger safely;
- how to build idempotent sync requests;
- how to interpret sync responses;
- example payloads for common accounting events;
- sandbox startup instructions;
- what not to bypass.

## Recommended client flow

1. Create or update the local business record in your system.
2. Build a stable `external_id` for that logical event.
3. Generate an `Idempotency-Key` that stays stable across retries for the same request.
4. Send the sync-event envelope to `POST /api/v1/sync-events/`.
5. Treat `200 OK` and `201 Created` as success.
6. Treat `409 Conflict` as a duplicate or payload-mismatch signal and reconcile before retrying.

## Example payloads

All examples use the generic sync-event envelope. The `payload` object holds the business-specific detail.

### Tenant charge

```json
{
  "source_system": "propertyledger",
  "domain_event_type": "tenant_charge.created",
  "external_id": "tenant_charge:123",
  "source_object_type": "tenant_charge",
  "source_object_id": "123",
  "occurred_at": "2026-07-16T12:00:00Z",
  "payload": {
    "property_id": 10,
    "lease_id": 42,
    "tenant_id": 7,
    "charge_type": "base_rent",
    "amount": "1250.00",
    "description": "July rent",
    "due_date": "2026-08-01"
  }
}
```

### Tenant payment

```json
{
  "source_system": "propertyledger",
  "domain_event_type": "tenant_payment.received",
  "external_id": "tenant_payment:555",
  "source_object_type": "tenant_payment",
  "source_object_id": "555",
  "occurred_at": "2026-07-16T15:30:00Z",
  "payload": {
    "tenant_id": 7,
    "property_id": 10,
    "amount": "1250.00",
    "payment_method": "cash",
    "reference_number": "RCPT-2026-07-16-01",
    "applied_invoice_ids": [88]
  }
}
```

### Vendor bill

```json
{
  "source_system": "propertyledger",
  "domain_event_type": "vendor_bill.created",
  "external_id": "vendor_bill:9001",
  "source_object_type": "vendor_bill",
  "source_object_id": "9001",
  "occurred_at": "2026-07-16T16:00:00Z",
  "payload": {
    "vendor_id": 31,
    "property_id": 10,
    "unit_id": 22,
    "bill_date": "2026-07-16",
    "due_date": "2026-08-15",
    "amount": "245.00",
    "category": "repairs_and_maintenance",
    "description": "Replace hallway lockset"
  }
}
```

### Manual management-fee expense

```json
{
  "source_system": "propertyledger",
  "domain_event_type": "management_fee_expense.recorded",
  "external_id": "management_fee_expense:77",
  "source_object_type": "management_fee_expense",
  "source_object_id": "77",
  "occurred_at": "2026-07-16T17:00:00Z",
  "payload": {
    "property_id": 10,
    "amount": "150.00",
    "expense_date": "2026-07-16",
    "description": "Monthly management fee",
    "notes": "Manual expense recorded by bookkeeper"
  }
}
```

## Error handling

- If the request is valid, keep the same `Idempotency-Key` on network retries.
- If the server returns `409 Conflict`, do not blindly retry with the same payload; inspect whether the key was reused incorrectly.
- If validation fails, fix the payload first.
- If the upstream accounting action failed after the sync record was created, surface the failure to a human and retry only after the source issue is resolved.

## Do not bypass the adapter boundary

External clients should not:

- write directly to database tables;
- assume UI routes are public APIs;
- infer LedgerOS posting success from a sync record alone;
- invent non-documented endpoint contracts.

## Sandbox setup

Use the documented Docker workflow.

1. Start the app:

```bash
make up
```

2. Apply migrations and bootstrap settings:

```bash
make migrate
```

3. Run the smoke checks:

```bash
make smoke
```

4. Confirm the runtime is healthy:

- `GET /api/health/local/`
- `GET /api/health/ledgeros/`

## Environment variables

These values matter for connector and sync behavior:

- `LEDGEROS_BASE_URL`
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

## See also

- [API reference](./api.md)
- [Epic 10 decision record](./epic-10.md)
- [LedgerOS integration contract](./ledgeros-integration-contract.md)

