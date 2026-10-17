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

On the Properties, Units, Tenants, and Leases lists, choose **View** to review a record without opening an editing form. Choose **Edit** when you want to make changes. Detail pages also provide an Edit link and a Back to list link.

### 3. Add tenant charges

Use tenant charges for recurring rent and manual charges.

Examples:

- monthly base rent;
- utility reimbursement;
- late fee;
- other manual charge.

### 4. Record tenant payments

Use tenant payments to record money received from tenants and apply it to open invoices.

Allocating a payment posts its invoice allocations to LedgerOS. Choose **Retry
and finalize payment** to retry failed allocations and confirm the complete
receipt. Successfully posted allocations are reused. The full receipt must be
allocated before it can be finalized; any excess remains unapplied locally.
After posting has been attempted, accounting fields are locked and notes remain
editable. If an attempt fails, retry the existing payment rather than creating
a replacement receipt.

### 5. Record vendor bills and payments

Use vendor records for payees and vendor bills for expenses.

You can also record vendor payments and debt-service payments when those workflows apply.

The Vendor Bills list and bill detail page show **Payment status**, **Amount
paid**, **Credits applied**, and **Balance due** from LedgerOS. These include
payments and vendor credits applied to the bill directly in LedgerOS. Payment
status is separate from the bill's posting status.

Use the **Payment status** selector and **Filter** button to find unpaid,
partially paid, or paid bills. Choose **All statuses** or **Clear filter** to
return to the full list. The maintenance summary continues to cover all bills.

**Not posted** means the bill has not posted. **Unavailable** means its current
balance could not be read; it does not mean unpaid. **Needs review** indicates
a reconciliation problem, such as an older credit-card payment whose journal
has not yet been linked to the bill. Ask an administrator to reconcile that
existing payment rather than creating another one. General journal adjustments
without a bill allocation are not included in the bill's balance.

To record a payment, open a synced bill and choose **Pay bill**. The vendor and
bill are fixed, the amount defaults to the current balance, and the date defaults
to today. Review the payment method, funding account, amount, and any check or
memo details, then choose **Post payment**. You may enter a smaller amount for a
partial payment. Opening the form does not post anything.

After submission you return to the bill with its refreshed balance and payment
status. If posting fails, the saved payment appears under **Payments awaiting
confirmation**. Choose **Retry payment** to reuse that payment. Repeating the
same form submission also reuses the original payment; do not create a new one
to recover from a timeout. Bookkeepers and admins can submit payments; read-only
users can review bills and payment records.

Bills that are unsynced, voided, fully settled, unavailable, or awaiting
reconciliation cannot start a new payment. The page explains the reason.

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

