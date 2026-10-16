# Epic 4 Runbook

## Purpose

This document contains the working guide for Epic 4 in PropertyLedger.

Epic 4 adds the payments app and its two core workflows:

- manual tenant payments;
- payment application to open tenant invoices;
- payment sync handoff to LedgerOS;
- security deposit events;
- security deposit balance tracking derived from event records;
- security deposit sync handoff to LedgerOS.

Payment syncs are accounting mutations, not audit-only event writes. A successful tenant payment sync must result in the appropriate LedgerOS posted accounting change, including the cash or clearing account and the matching accounts receivable reduction, according to the LedgerOS payment contract.

Epic 4 does not include:

- online rent collection;
- ACH/card payment processing;
- payment webhooks;
- failed-payment automation;
- tenant portal payments;
- vendor payments;
- check writing;
- deposit-interest rules;
- jurisdiction-specific deposit compliance.

## Files To Know

- [`README.md`](../README.md)
- [`Makefile`](../Makefile)
- [`.env.example`](../.env.example)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docs/propertyledger-prd.md`](../docs/propertyledger-prd.md)
- [`docs/propertyledger-implementation-epics.md`](../docs/propertyledger-implementation-epics.md)
- [`docs/epic-3.md`](../docs/epic-3.md)
- [`docs/epic-3-lessons-learned.md`](../docs/epic-3-lessons-learned.md)
- [`payments/models.py`](../payments/models.py)
- [`payments/services.py`](../payments/services.py)
- [`payments/views.py`](../payments/views.py)
- [`payments/forms.py`](../payments/forms.py)
- [`payments/tests/test_payments_workflow.py`](../payments/tests/test_payments_workflow.py)

## Required Environment Variables

Use the same environment variables as the rest of PropertyLedger.

## Start Up

Use Docker Compose only.

1. Start the PropertyLedger stack:

```bash
make up
```

2. Run migrations and bootstrap settings:

```bash
make migrate
```

3. Run the smoke checks:

```bash
make smoke
```

4. Open the payments app at:

- `http://localhost:8000/payments/`

## Domain Rules

### Tenant payments

- Payments may be saved as draft without invoice applications.
- Invoice applications are added after save on the payment detail screen.
- Application uses a global invoice-type priority order.
- Within each invoice type, oldest open invoices are applied first.
- Payment accounting fields are immutable after an allocation has been attempted; notes remain editable.
- Payment sync requires full application and successful invoice-application syncs.
- Payment sync is only complete when LedgerOS has posted the accounting effect of the receipt.

### Security deposits

- Security deposit balance is derived from event records.
- Event types include required, received, deducted, and refunded.
- Each event syncs independently.
- Synced deposit events are immutable except for the non-accounting note field.

## LedgerOS Contract

Tenant invoice creation uses `POST /api/v1/invoices/`. Tenant payment
applications use `POST /api/v1/payments/` with the invoice reference, payment
date, and allocated amount. LedgerOS posts debit Cash / credit AR and reduces
the invoice balance. A payment spanning several invoices creates one LedgerOS
payment per allocation.

Receipt finalization is local: it retries failed allocations with their existing
idempotency keys, skips confirmed posted allocations, and succeeds only when the
full receipt is allocated and posted. A generic `tenant_payment.received` event
is no longer required. Legacy receipt events remain as history; a separate local
`tenant_payment.finalized` summary references the posted payment/journal IDs.

Security deposit events continue to use `POST /api/v1/sync-events/`. The generic
event endpoint alone is not proof of posted accounting.

See the [Technical Manual](../technical-manual.md) for current retry,
immutability, and compatibility rules.

## Testing

Run tests in Docker only.

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test payments.tests.test_payments_workflow
```

The automated suite stubs the LedgerOS transport in-process; there is no separate human-facing mock LedgerOS mode.

Run Django checks in Docker:

```bash
make check
```

## Manual Checks

- Create a draft tenant payment.
- Add invoice applications on the detail page.
- Confirm application order follows the configured invoice-type priority.
- Confirm sync is blocked until the payment is fully applied to open invoices.
- Confirm a successful payment sync changes LedgerOS posted balances, not just the sync event log.
- Record security deposit events and confirm the balance is derived from the event stream.

## Bootstrap

Use `./scripts/dev-bootstrap.sh` to seed the shared LedgerOS configuration and payment workflow settings.
