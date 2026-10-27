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

### Workflow home and navigation

After signing in, everyone starts at `/home/`. Choose **Collect Rent / Deposit**, **Get Billed & Pay Vendors**, or the maintenance card. Available links reflect your existing role. The sidebar keeps records, payments, reports and authorized administration pages reachable. Collapse it on desktop, or use **Menu** on mobile; Escape closes the mobile menu and returns focus to its button.

The home shows actual saved receipts awaiting finalization, attempted vendor payments awaiting confirmation, and active maintenance requests, with up to five entries per queue. These are local workflow counts, not accounting balances. Viewers receive read links; accounting actions require a bookkeeper or administrator. An account without an assigned role displays guidance instead of records.

Setup stays at `/` for administrators. The home shows setup and connection status separately. During a connection failure it labels accounting balances unavailable; it does not substitute zero. Open the existing bill or banking screen to read current LedgerOS balances.

Vendor bills use independent approval and individual payment authorizations. Maintenance requests use a separate local operational lifecycle. Tenant receipts may combine invoice payments and refundable security deposits, with each component confirmed separately by LedgerOS.

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

Use tenant payments to record money received from tenants. Enter the full receipt amount. If part is a refundable security deposit, enter that amount and choose the matching lease; the remainder can be allocated to open invoices.

Allocating posts invoice components to LedgerOS. Choose **Retry components and
finalize receipt** to post the deposit component, retry failures, and confirm the
receipt. Successfully posted components are reused. The full amount must be split
between invoices and the deposit before finalization; any remainder stays
unallocated locally. After any posting attempt, accounting fields are locked and
notes remain editable. Retry the existing receipt after a timeout or partial
failure rather than creating a replacement.

### 5. Record vendor bills and payments

Use vendor records for payees and vendor bills for expenses.

Set a vendor's payment terms to **15 days**, **30 days**, or **Upon receipt**. New bills default to today's bill date and a due date calculated from that date using the vendor's terms; unset terms mean the same day. On new bill forms, changing the vendor or bill date updates the suggested due date until you enter your own due date. Both dates remain editable before posting. Existing bills keep their saved dates when vendor terms change.

Enter the supplier's reference in **Vendor invoice number** (optional). It appears on the bill detail page and is sent to LedgerOS when a new bill is posted. Changing it on an approved, unposted bill requires approval again. Previously posted bills are not automatically updated in LedgerOS.

You can also record vendor payments and debt-service payments when those workflows apply.

New vendor bills are saved locally first. Choose **Save draft** while entering or correcting a bill, or **Save and submit for approval** when it is ready for review. The submitter cannot approve the same bill. A separately authorized approver opens the approval queue, reviews the bill, and approves or rejects it. Rejected bills can be corrected and resubmitted.

Approval does not post the bill. After approval, an administrator or bookkeeper explicitly chooses **Post approved bill**. The bill must be both approved and successfully posted before a new payment can begin. Approval status, posting status, and payment status appear separately.

Payment-authorized users open an approved posted bill and choose **Pay bill**. Bill approvers do not automatically have payment authority, and payment-authorized users do not automatically receive approval authority. Administrators configure both grants separately under **Workflow authorizations**.

Existing posted bills created before this workflow show **Legacy / approval not recorded**. Submit one for prospective approval before recording another payment. This does not repost the bill or rewrite its accounting history.

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

### 6. Track maintenance work

Open **Maintenance** from the sidebar or the home card. Administrators, property managers, and bookkeepers can create requests. Property, description, category, and priority are required. Unit, tenant, vendor, target completion date, and estimated cost are optional. If you select a tenant, that tenant must have a lease for the selected property and unit.

Move work through **Open → Triaged → Assigned → In progress → Verified → Closed**. A vendor is required before assignment. Work may be placed on hold with a reason and resumed to its prior state. Verify completed work before closing it. At closure, record whether a vendor invoice is still pending or the work had no external cost, and add a closure note.

Closing maintenance does not wait for an invoice or payment. If work returns, reopen the closed request with a reason; it returns to Triaged while the prior closure remains in history. Read-only viewers can review requests but cannot change them. Owner viewers do not receive maintenance access.

Maintenance requests save locally during a LedgerOS outage and do not create accounting entries. Photo uploads are unavailable until the deployment has approved private durable storage and image validation.

When an invoice arrives, open the maintenance request. Admins and bookkeepers can choose **Create vendor bill**; the form prefills safe request context for review and creates nothing until submitted. Admins, property managers, and bookkeepers can instead link a compatible existing bill. Property and unit must match. Repeated submission reuses the first bill rather than creating a duplicate.

One request can show multiple vendor bills. Each row displays approval, posting, and payment separately. Bills can be created or linked before work is verified or after it is closed. Linking a bill does not change maintenance status, and closing maintenance does not approve, post, or pay a bill. Use the vendor bill page for those financial actions.

### 7. Track deposits

Security deposit activity comes from confirmed receipt deposit components and standalone received/refunded events. Deposit money is a liability and does not appear as rent collection or tenant AR settlement.

### 8. Review reports and owner statements

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

# Working during a LedgerOS outage

The header and workflow home distinguish incomplete PropertyLedger setup, incomplete LedgerOS configuration, denied access, and a service outage. You may continue local maintenance work and save receipt or vendor-bill drafts. Posting allocations, finalizing receipts, posting bills, paying vendors, and other accounting actions remain disabled until LedgerOS is ready. Accounting-derived amounts appear as **Unavailable**, never as zero. After recovery, retry the same saved record so PropertyLedger reuses its accounting identity; do not create a replacement record.

