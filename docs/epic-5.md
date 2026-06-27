# Epic 5 Runbook

## Purpose

This document contains the working guide for Epic 5 in PropertyLedger.

Epic 5 adds:

- vendor records;
- vendor bills;
- maintenance categories and maintenance expense summary;
- vendor payments, including credit-card-paid vendor bills;
- credit-card payoff workflow from bank account;
- manual debt-service payments with principal and interest split.

Epic 5 does not include:

- work orders;
- tenant maintenance requests;
- vendor dispatch;
- photos or receipt OCR;
- an approval workflow separate from sync;
- automatic credit-card feed ingestion;
- automatic card statement reconciliation;
- amortization schedule generation;
- automatic principal/interest split calculation.

## Files To Know

- [`README.md`](../README.md)
- [`docs/propertyledger-prd.md`](../docs/propertyledger-prd.md)
- [`docs/propertyledger-implementation-epics.md`](../docs/propertyledger-implementation-epics.md)
- [`docs/epic-4-lessons-learned.md`](../docs/epic-4-lessons-learned.md)
- [`payments/models.py`](../payments/models.py)
- [`payments/forms.py`](../payments/forms.py)
- [`payments/services.py`](../payments/services.py)
- [`payments/views.py`](../payments/views.py)
- [`payments/urls.py`](../payments/urls.py)
- [`payments/admin.py`](../payments/admin.py)
- [`payments/tests/test_payments_workflow.py`](../payments/tests/test_payments_workflow.py)

## Required Environment Variables

Use the same environment variables as the rest of PropertyLedger.

## Startup

Use Docker Compose only.

1. Start the PropertyLedger stack:

```bash
make up
```

2. Run migrations:

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

### Vendors and maintenance categories

- Vendors are local master data for payees and lenders.
- Maintenance categories are reporting labels for vendor bills.

### Vendor bills

- Bills may be created for a property and optional unit.
- Bills may be tagged with a maintenance category.
- Repair notes are accounting-relevant.
- After save, a bill should move directly to sync when required mappings are present.
- Synced bills are immutable except for non-accounting note fields.

### Vendor payments

- Vendor payments reference a vendor bill.
- Payments may be recorded by check, ACH, cash, or other manual methods.
- Credit-card-paid vendor bills use credit-card liability accounting.
- Credit-card payoff uses bank cash and reduces credit-card liability.
- Synced vendor payments are immutable except for non-accounting note fields.

### Debt service

- Debt-service payments require principal plus interest to equal the total.
- Debt-service sync uses the required liability, interest, and operating bank mappings.
- Synced debt-service payments are immutable except for non-accounting note fields.
- Vendor bill sync upserts the vendor on LedgerOS before posting the bill so the bill path does not depend on a preseeded backend vendor record.

## LedgerOS Contract

Epic 5 uses the LedgerOS endpoint that matches the accounting object being posted:

- `POST /api/v1/vendors/` for vendor provisioning
- `POST /api/v1/bills/` for vendor bills
- `POST /api/v1/payments/` for standard vendor bill payments
- `POST /api/v1/sync-events/` for journal-entry-backed liability workflows such as credit-card vendor payments, credit-card payoff, and debt-service payments

Source event types:

- `vendor_bill.created`
- `vendor_payment.sent`
- `vendor_payment.credit_card`
- `credit_card.payoff`
- `debt_service.payment_recorded`

LedgerOS turns the supported sync-event liability workflows into posted journal entries.

## Testing

Run the Epic 5 test slice in Docker:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test payments.tests.test_payments_workflow
```

Run Django checks in Docker:

```bash
make check
```

## Manual Checks

- Create a vendor and maintenance category.
- Confirm the first vendor sync provisions the vendor in LedgerOS.
- Create a vendor bill for a property and optional unit.
- Confirm the bill syncs to LedgerOS.
- Record a vendor payment by credit card and confirm it posts the expected accounting effect.
- Record a credit-card payoff and confirm it reduces credit-card liability.
- Record a debt-service payment with principal and interest split.
- Confirm synced records are not destructively editable.
