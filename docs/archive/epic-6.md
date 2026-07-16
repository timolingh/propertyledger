# Epic 6 Runbook

## Purpose

This document contains the working guide for Epic 6 in PropertyLedger.

Epic 6 adds:

- read-only visibility into LedgerOS bank accounts;
- read-only visibility into LedgerOS reconciliation status;
- a safe place to reserve later check-writing work without implementing it in MVP.

Epic 6 does not include:

- Plaid or other bank feeds;
- automatic statement import;
- external bank event ingestion;
- automated reconciliation matching;
- reconciliation actions beyond visibility;
- printable check generation in MVP;
- check-writing implementation unless explicitly expanded later.

## Decision Log

The Epic 6 decision log has been incorporated into the documented MVP boundary:

- Scope for this pass: MVP banking and reconciliation visibility only
- Missing LedgerOS banking API handling: add the narrow API only if a required surface is absent
- Reconciliation scope for this pass: visibility only
- Deposit and withdrawal payloads: whatever LedgerOS already exposes
- No LedgerOS code change was required for the current MVP visibility pass

## Files To Know

- [`README.md`](../README.md)
- [`docs/propertyledger-prd.md`](propertyledger-prd.md)
- [`docs/propertyledger-implementation-epics.md`](propertyledger-implementation-epics.md)
- [`payments/services.py`](../payments/services.py)
- [`payments/views.py`](../payments/views.py)
- [`payments/urls.py`](../payments/urls.py)
- [`payments/templates/payments/banking.html`](../payments/templates/payments/banking.html)
- [`payments/tests/test_banking_visibility.py`](../payments/tests/test_banking_visibility.py)

## Current Status

Epic 6 MVP banking visibility is implemented against the existing LedgerOS API surface.

The PropertyLedger app now:

- reads bank-account summaries from LedgerOS;
- reads reconciliation summaries from LedgerOS;
- renders a protected banking visibility page for logged-in users;
- exposes the page from the Payments landing page and the global header.

## Domain Rules

### Banking visibility

- The banking page is read-only in MVP.
- The page must not accept bank-feed ingestion or reconciliation mutations.
- Bank-account balances come from LedgerOS read APIs.
- Reconciliation status comes from LedgerOS read APIs.

### Check writing

- Check writing remains deferred in MVP.
- The MVP data model should continue to preserve a later drop-in path for check writing.

## LedgerOS Contract

PropertyLedger uses the existing LedgerOS banking endpoints:

- `GET /api/v1/bank-accounts/`
- `GET /api/v1/bank-reconciliations/`

These calls use the same authenticated adapter pattern as the other PropertyLedger LedgerOS requests.

## Testing

Run the Epic 6 test slice in Docker:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test payments.tests.test_banking_visibility
```

Run Django checks in Docker:

```bash
make check
```

## Manual Checks

- Open the Payments landing page and confirm the Banking visibility link is present.
- Open the Banking visibility page and confirm bank-account summaries render.
- Open the Banking visibility page and confirm reconciliation summaries render.
- Confirm the page remains read-only.
