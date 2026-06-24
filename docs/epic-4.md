# Epic 4 Runbook

## Purpose

This document contains the working guide for Epic 4 in PropertyLedger.

Epic 4 adds the payments app and its two core workflows:

- manual tenant payments;
- payment allocation across open tenant charges;
- payment sync handoff to LedgerOS;
- security deposit events;
- security deposit balance tracking derived from event records;
- security deposit sync handoff to LedgerOS.

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

- Payments may be saved as draft without allocations.
- Allocations happen after save on the payment detail screen.
- Allocation uses a global charge-type priority order.
- Within each charge type, oldest charges are allocated first.
- Synced payments are immutable except for the non-accounting note field.
- Payment sync requires full allocation and successful application syncs.

### Security deposits

- Security deposit balance is derived from event records.
- Event types include required, received, deducted, and refunded.
- Each event syncs independently.
- Synced deposit events are immutable except for the non-accounting note field.

## LedgerOS Contract

Epic 4 expects the sibling LedgerOS repo to expose a generic sync-event API:

- `POST /api/v1/sync-events/`

PropertyLedger sends one generic event envelope per downstream accounting event:

- `source_system = "propertyledger"`
- `domain_event_type` for the business event name, such as `tenant_payment.received` or `security_deposit.received`
- `external_id` as a stable unique ID for the local object, event, or version
- `source_object_type` as the local model name
- `source_object_id` as the local primary key
- `occurred_at` as the original event timestamp
- `payload` as the full property-specific event details

If that endpoint is missing in LedgerOS, update the sibling LedgerOS repo first. PropertyLedger should not fall back to a journal-only implementation for Epic 4 sync.

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
- Add allocations on the detail page.
- Confirm allocation order follows the configured category priority.
- Confirm sync is blocked until the payment is fully allocated.
- Record security deposit events and confirm the balance is derived from the event stream.

## Bootstrap

Use `./scripts/dev-bootstrap.sh` to seed the shared LedgerOS configuration and payment workflow settings.
