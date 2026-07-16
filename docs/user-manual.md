# PropertyLedger User Manual

## Purpose

This manual is for property managers, bookkeepers, and other day-to-day users of PropertyLedger.

## What PropertyLedger does

PropertyLedger helps manage the accounting side of real estate operations.

You can use it to:

- set up properties, units, owners, tenants, and leases;
- generate base rent and record manual tenant charges;
- record tenant payments and security deposits;
- track vendor bills, vendor payments, and debt-service payments;
- view owner statements and operational reports;
- check banking visibility from LedgerOS;
- keep accounting activity aligned with LedgerOS.

## Roles in plain language

- Admin: sets up the system, LedgerOS connection, and mappings.
- Property manager: manages properties, units, tenants, leases, and operational records.
- Bookkeeper: records accounting activity, payments, bills, and reports.
- Read-only viewer: can review records and reports without changing them.

## Common tasks

### 1. Start with setup

Before entering day-to-day records, make sure the LedgerOS connection, entity, accounting period, and account mappings are configured.

### 2. Create your property records

Create records in this order:

1. owners
2. properties
3. units
4. tenants
5. leases

That order matters because later records depend on earlier ones.

### 3. Add tenant charges

Use tenant charges for recurring rent and manual charges.

Examples:

- monthly base rent;
- utility reimbursement;
- late fee;
- other manual charge.

### 4. Record tenant payments

Use tenant payments to record money received from tenants and apply it to open invoices.

### 5. Record vendor bills and payments

Use vendor records for payees and vendor bills for expenses.

You can also record vendor payments and debt-service payments when those workflows apply.

### 6. Track deposits

Security deposit activity is recorded as events and the balance is derived from those events.

### 7. Review reports and owner statements

Use reports to review:

- rent roll;
- tenant ledger;
- delinquency;
- property income and expense;
- owner statements;
- security deposit activity;
- maintenance summaries.

## What counts as synced

Some records are local until they are successfully synced to LedgerOS.

Rules of thumb:

- draft records can usually be edited more freely;
- synced records are more restricted;
- accounting totals should rely on synced data;
- unsynced items may appear in pending or diagnostic views.

## What not to do

- Do not assume a sync record alone means the accounting effect is posted.
- Do not edit synced records as if they were drafts.
- Do not bypass the setup order when a parent record is required first.
- Do not use UI pages as if they were a public integration API.

## Helpful habits

- Watch the status labels before editing or approving records.
- Use the setup screen and reports to confirm accounting readiness.
- If a workflow fails, check whether the issue is missing setup, missing mappings, or a LedgerOS connectivity problem.

## See also

- [Quick Start Guide](./quick-start.md)
- [Technical Manual](./technical-manual.md)

