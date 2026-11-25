# PropertyLedger user manual for bookkeepers and property managers

Use PropertyLedger to maintain your portfolio records, record tenant receipts and vendor payments, follow maintenance work, and review reports. This guide explains the screens and controls you use to complete those tasks.

PropertyLedger records payments you receive or make outside the application. Selecting a payment button does not send money to a vendor or collect money from a tenant. LedgerOS holds the accounting records; PropertyLedger shows the related property information and the result of sending a transaction to LedgerOS.

## Find the task you need

| Your task | Go to |
| --- | --- |
| Sign in and check your access | [Before your first session](#before-your-first-session) |
| Understand menus and forms | [Find your way around](#find-your-way-around) |
| Understand a transaction status | [Know what has been saved or posted](#know-what-has-been-saved-or-posted) |
| Add a tenant or lease | [Maintain portfolio records](#maintain-portfolio-records) |
| Record or update maintenance | [Manage maintenance work](#manage-maintenance-work) |
| Enter and post rent or another charge | [Create a tenant invoice](#create-a-tenant-invoice) |
| Record rent and deposit money received | [Record a tenant receipt](#record-a-tenant-receipt) |
| Check deposits or record a refund | [Review security deposits](#review-security-deposits) |
| Enter a supplier invoice | [Enter a vendor bill](#enter-a-vendor-bill) |
| Review a bill submitted by someone else | [Approve or reject a vendor bill](#approve-or-reject-a-vendor-bill) |
| Record a vendor payment | [Pay an approved bill](#pay-an-approved-bill) |
| Run reports or prepare an owner statement | [Review reports and owner statements](#review-reports-and-owner-statements) |
| Record financing or owner activity | [Record other financial activity](#record-other-financial-activity) |
| Correct a record or resolve a failure | [Correct mistakes and recover unfinished work](#correct-mistakes-and-recover-unfinished-work) |

## Before your first session

Ask your administrator for the PropertyLedger website address, your username and password, and confirmation that the correct LedgerOS books and account mappings are ready. Open that address in your web browser and sign in. Your starting page is **Home**.

Your account determines which controls appear. A missing button may mean you need additional authority, rather than that you have opened the wrong screen.

| Task | Property manager | Bookkeeper |
| --- | --- | --- |
| Create or edit owners, properties, units, tenants, and leases | Yes | Ask a manager or administrator |
| Create and progress maintenance requests | Yes | Yes |
| Link an existing bill to maintenance | Yes | Yes |
| Create a vendor, bill, tenant invoice, receipt, or deposit transaction | Ask a bookkeeper or administrator | Yes |
| Approve or reject a bill submitted by someone else | Separate approval authorization required | Separate approval authorization required |
| Record or retry a vendor bill payment | Separate payment authorization required | Separate payment authorization required |
| Review reports and owner statements | Yes | Yes |
| Open the Banking dashboard or record debt service and owner activity | Ask a bookkeeper or administrator | Yes |

Approval and payment authorizations are separate. Being a bookkeeper, manager, or administrator does not automatically grant both. You cannot approve a bill you submitted yourself.

If Home says **Setup incomplete**, or asks you to obtain an assigned role, send that message to your administrator before starting financial work. Local maintenance work can still be available during a LedgerOS connection failure.

## Find your way around

### Use Home and the sidebar

Home has three cards: **Collect Rent / Deposit**, **Get Billed & Pay Vendors**, and **Log Maintenance Request**. Select the action that matches your task. The sidebar on the left also provides record lists, maintenance, payments, reports, and authorized administration pages.

On a small screen, select **Menu** to open the sidebar and **Close menu** to close it. On a larger screen, **Collapse navigation** reduces its width. Select **Home** to return to your starting page.

**My Work Queues** contains links to unfinished work. Select a record to open it. The counts describe workflow records, not account balances, and the records are not necessarily assigned to you personally. Only five entries may be shown in a queue; use the relevant sidebar list to review more.

Two current labels need care: **Pay approved bills** opens the full bill list, so review the selected bill's approval and payment status. A maintenance queue can also have a footer saying **View all vendor payments** even though it opens maintenance; use **Maintenance** in the sidebar when the label is confusing.

### Read a list or use a form

A list contains saved records. Find the appropriate name, amount, date, or reference in the rows. If you need to locate text on a long page, your browser's Find command can help: press **Command F** on a Mac or **Ctrl F** on Windows, then enter the name or reference.

Select **View**, where provided, to inspect a record. Select **Edit** to change it. A numbered link such as **Bill 47**, **Payment 12**, or a maintenance request number also opens that saved record; note the number when asking for help.

On a form, select a field to type in it. Select a drop-down to choose an existing record. For dates, use the calendar control or enter the date in the format shown. Review suggested dates and amounts; they may need changing for your transaction.

Changes are not saved just because you type them. Use the form's save button. **Back**, **Cancel**, and navigation links leave the form; save first if you want to retain your changes. If the form stays on screen after submission, read the messages above it and beside the fields, correct the indicated entries, and submit the same form again.

After submitting a financial action, wait for the result. If the browser asks to resend a form when you refresh, return to the saved record through the sidebar and inspect its status before taking another action.

## Know what has been saved or posted

| Label or action | What it tells you |
| --- | --- |
| **Draft** or **Save draft** | The record is held in PropertyLedger. A saved draft is not proof of a LedgerOS posting. |
| **Save receipt for review** | Saves the receipt and its allocation for review. It does not post the receipt. |
| **Submitted** | A vendor bill is waiting for independent review. |
| **Approved** on a vendor bill | Approval is recorded. Posting and payment are still separate steps. |
| **Post approved bill** | Attempts to record the approved vendor bill in LedgerOS. |
| **Approve and post to LedgerOS** on a tenant invoice | Approves and attempts to post that invoice in the same action. |
| **Synced** or **Posted** | Read this in context: a tenant/vendor sync confirms customer/payee setup; a financial transaction needs its own posting confirmation. A posted bill can still be unpaid. |
| **Allocated** or **Assigned** on a receipt | Money has been assigned to a purpose. Check the separate posting results before treating it as posted. |
| **Unavailable** | A current accounting amount or status could not be obtained. It does not mean zero or unpaid. |
| **Needs review**, **Not confirmed**, or a failure message | Review the record and its explanation before further posting or collection. |

Vendor bills show three distinct results: **Approval status**, **Bill posting status**, and **Payment status**. Review all three. Receipts can have separate invoice, deposit, and Other results; one successful part does not mean every part succeeded.

## Maintain portfolio records

**For property managers.** Prepare records before asking a bookkeeper to enter invoices or payments for them.

### Add the records in order

Use **Records** in the sidebar. Before adding anything, check the relevant list to avoid a duplicate.

| Record | Where to start | What to enter and save |
| --- | --- | --- |
| Owner | **Owners → Add owner** | Name and available contact details; select **Create owner**. |
| Property | **Properties → Add property** | Name, primary owner, status, and notes; select **Create property**. |
| Unit | **Units → Add unit** | Property, unit name, status, and notes; select **Create unit**. |
| Tenant | **Tenants → Add tenant** | Name and contact details; select **Create tenant**. Creation also sets up the LedgerOS customer. |
| Lease | **Leases → Add lease** | Unit, tenant, lease dates, rent effective date, monthly rent, deposit requirement, and status; select **Create lease**. |

Use **Active** for a lease that should be in current operation. Enter the deposit requirement on the lease even when no deposit has been collected. That requirement does not record a receipt or create a deposit invoice.

After saving a property, unit, tenant, or lease, use **View** in its list to confirm the saved details. For an owner, use **Edit** to inspect its details if needed and leave without saving if nothing changes. Hand the bookkeeper the tenant, property/unit, lease, agreed rent, and effective dates.

If creating a property or tenant reports a LedgerOS error, resolve the error on the current form; that creation may not have been saved. Check the list before starting another record.

### Resolve a tenant customer setup problem

If a bookkeeper reports **Unknown customer** while posting an invoice:

1. Open **Tenants**, find the tenant, and select **View**.
2. Select **Provision in LedgerOS**.
3. Review the tenant name, customer code, and default AR account. The customer code is supplied by the application; do not invent a replacement.
4. Select **Provision in LedgerOS** on the review page.
5. Confirm **Tenant customer provisioned in LedgerOS**, then ask the bookkeeper to retry the original invoice.

If the page reports a conflicting name, account, or inactive customer, ask the administrator to resolve it. Editing and saving the tenant's name alone does not perform this provisioning step. Provisioning does not post the failed invoice for you.

## Manage maintenance work

**For managers and bookkeepers.** Maintenance completion and vendor billing are tracked independently.

### Create and find a request

1. Select **Maintenance** in the sidebar, then **New request**.
2. Choose the property, category, and priority, and describe the work.
3. Add unit, tenant, vendor, target date, and estimate when applicable. Leave the unit blank for property-wide work. Check any property/unit values filled after another selection.
4. Select **Create request**.
5. On the request, confirm the description, location, and **Open** status. Note its request number.

To return later, open **Maintenance** and select the request number/description. Use the **Status** selector and **Filter** to narrow the list; select **All statuses** and **Filter** to remove that restriction. Photo uploads are not currently available.

### Progress the work

Open the request and use **Operational actions**. Only actions appropriate to its current state appear.

| When the work is ready for this step | Select |
| --- | --- |
| Review and triage the new request | **Mark triaged** |
| Assign responsibility to a vendor | Choose the vendor, then **Assign vendor** |
| Begin the assigned work | **Start work** |
| Confirm that the work is complete | **Verify completion** |
| Finish the operational record | Choose the invoice outcome, enter a closure note, then **Close request** |

At closure, choose **Vendor invoice pending** if the invoice has not arrived, or **No external cost** where appropriate. A vendor bill or payment is not required to close verified work.

For a delay, select **Put on hold** with a reason; **Resume work** returns it to the preceding work stage. To reopen a closed request, enter the reason and select **Reopen request**; it returns to **Triaged** and retains the earlier closure in **History**. **Cancel request** requires a reason; a cancelled request has no supported reopen action. If the page says another person changed the request, reopen it from the list and review the latest details before trying again.

### Connect a vendor invoice to the request

If the bill is already entered, do not enter it again:

1. Open the maintenance request and find **Financial status**.
2. Under **Link an existing bill**, select the bill and choose **Link bill**.
3. Confirm it appears in the linked-bills table.

The bill must match the property and, for a unit-specific request, that unit. If an expected bill is missing from the selection, ask the bookkeeper to check its attribution and whether it is already linked elsewhere.

If the bill has not been entered, a bookkeeper can select **Create vendor bill** on the request, review the suggested details, and use the bill procedure below. Managers can link suitable existing bills but cannot create bills from this screen with their manager role alone.

Several vendors' bills can link to one request, including after closure. The request's bill table shows approval, posting, and payment separately. Open the bill itself for **Amount paid**, **Credits applied**, **Balance due**, or a reconciliation explanation; the maintenance table does not show every payment detail. Linking or unlinking a bill changes its association, not its accounting posting or the maintenance completion state.

## Create a tenant invoice

**For bookkeepers.** Enter monthly rent manually through these screens; there is no visible automatic monthly rent-generation control. A manager must prepare the tenant and lease first.

1. On Home, select **Create charge / invoice**, or select **Invoices → Add invoice** in the sidebar.
2. Choose the lease and **Charge type**. The lease identifies the tenant, property, and unit.
3. Enter the amount, charge date, and due date. For base rent, enter the billing period start and end as well. Check every date and amount rather than assuming they have defaulted to the lease terms.
4. Enter a useful description and keep **Status** as **Draft** while preparing the invoice.
5. Select **Create invoice**. Find that invoice in the list and select **View**.
6. Review the saved invoice. In **LedgerOS Sync**, select **Approve and post to LedgerOS** when ready to post.
7. Confirm **Invoice posted to LedgerOS** and a successful sync result. If posting failed, read the message and retry this same invoice after the cause is resolved.

If you opened **Edit invoice**, select **Save invoice** before using its separate posting button; the posting button uses saved values. An **Unknown customer** error requires the manager's provisioning procedure above, followed by an explicit retry of the original invoice.

For several saved invoices, the **Invoices** list also offers checkboxes, **Bulk action**, and **Apply**. Select only the invoices you have reviewed, choose **Approve and post to LedgerOS**, then **Apply**. Inspect each invoice's result afterward; a bulk approval message alone is not proof that every posting succeeded.

## Record a tenant receipt

**For bookkeepers.** Record the full amount actually received once, then review how it is allocated.

### Start from Home or an invoice

From Home, select **Record rent / deposit receipt**. From a posted invoice, select **Record payment**, then **Record receipt and review allocation**. Both paths lead to the same receipt form; invoice entry supplies the starting tenant/property context.

1. Confirm the property and tenant.
2. Enter **Payment date** and **Amount received** for the entire receipt.
3. Under **Allocate amount received**, review **Open invoices**, **Deposit**, and **Other**. Select **Deposit lease** if any amount is a deposit.
4. Check the payment method, reference, and notes.
5. Select **Save receipt for review**.
6. On the saved **Tenant Receipt**, compare the total with invoice allocations, deposit, Other, and **Unapplied balance**.
7. If the full amount is allocated correctly, select **Post receipt to LedgerOS**.
8. Confirm **Posted** and check the invoice, deposit, and Other confirmations that apply. Keep the receipt number with your payment reference.

To inspect the suggested invoice order, expand **Open invoices in allocation order** on the form. It includes invoiced late fees and pays oldest due dates first. If the proposed split is wrong, change the allocation before posting. Enter **0** to skip a category. A positive **Other** amount needs an **Other account code**; use the correct approved account, not a substitute for AR or deposit allocation.

One receipt can include several invoices, one deposit lease, and one Other account. The deposit portion cannot be split between leases on this screen. Ask for assistance before posting if that limit prevents the required allocation.

### Example of one payment covering rent and deposit

Suppose a tenant has a posted 1,800 rent invoice and a remaining deposit requirement of 900, and you receive one payment of 2,700. Use the tenant and actual dates applicable to your transaction.

| Receipt field | Example amount |
| --- | ---: |
| Amount received | 2,700.00 |
| Open invoices | 1,800.00 |
| Deposit | 900.00 |
| Other | 0.00 |
| Unapplied balance after saving | 0.00 |

Save the receipt, review it, then post it. The deposit confirmation belongs to this receipt. Do not also create a standalone deposit event for that 900.

### Leave an incomplete allocation for later

You can select **Save receipt for review** while money remains unapplied. That saves unfinished work; it does not post a tenant credit. Return through **Tenant receipts**, open the receipt, and select **Review receipt allocation**. Finish the split before posting. **Save and post receipt**, when offered on an existing receipt, both saves and attempts posting.

If rent has already posted on an older receipt and money remains unused, review the allocation on that same receipt. Confirm the posted invoice amount remains fixed, assign the remaining amount appropriately, save, then post the receipt. Do not create another receipt for those funds.

### Recover a receipt that did not fully post

Open the saved receipt and read its component results. A deposit or Other part may say **Not confirmed** even when an invoice application succeeded. Resolve the displayed error, then select **Post receipt to LedgerOS** on that same receipt. Confirmed parts are retained on retry.

Attempted allocations may be locked. If the application says a posting is uncertain or an attempted split cannot change, ask the administrator to reconcile the existing receipt. Do not work around the restriction with a new receipt or standalone deposit event.

## Review security deposits

Select **Security deposits** in the sidebar. Under **Deposit collection by lease**, compare **Required by lease**, **Confirmed received**, and **Remaining to collect**. Use **Deposit activity** to open the source receipt or standalone event.

The remaining amount concerns initial collection against the lease requirement; it is not the current deposit-liability balance. A refund, deduction, uncertain posting, or excess can require review before further collection. A draft **Received** event is not confirmed money received. If the lease shows **Needs review**, inspect its activity with the bookkeeper before collecting or posting more.

### Record a separate receipt or refund event

For a deposit receipt included in a tenant receipt, use that receipt's posting action. Use a standalone event only for a separate transaction, such as a refund not already recorded elsewhere.

1. Select **Add standalone deposit event**.
2. Enter the property, unit, tenant, lease, event type, actual event date, amount, description, and notes. Check that the selections describe the same tenancy.
3. Select **Save event**. This saves the event; it does not post it.
4. Review the saved event, then select **Sync event** under **Post standalone event** when ready.
5. Confirm the completion message and posting result. If it fails, resolve the cause and use **Sync event** on the existing event.

Only **Received** and **Refunded** events have supported posting. Do not use **Required** or **Deducted** to force an accounting entry; ask the administrator/bookkeeper responsible for the accounting correction to arrange the supported treatment. A refund entry records a refund already made outside the application.

## Enter a vendor bill

**For bookkeepers.** Find the existing bill before entering a new one, especially when returning after an error.

### Prepare the vendor

Open **Vendors** in the sidebar. If the payee already exists, check its **LedgerOS status**. Use **Sync to LedgerOS** or **Retry sync** when needed and confirm **Synced** before posting a bill for that vendor.

To add a missing payee, select **Add vendor**, enter the name/contact details and payment terms, and select **Create vendor**. Vendor saving attempts LedgerOS setup. If the message says it was saved locally or provisioning is pending, resolve the stated problem and retry the existing vendor. Vendor setup does not post a bill or payment.

### Save and submit the invoice

1. Select **Vendor payables** in the sidebar, then **Add bill**. For work linked to maintenance, instead use **Create vendor bill** on that request.
2. Select the vendor, property, and unit where applicable.
3. Enter **Vendor invoice number**, bill date, due date, amount, expense category, and relevant maintenance category/repair notes. Review suggested dates; vendor terms affect the suggested due date until you override it.
4. Check any **Tenant chargeable** designation against your organization's policy. Do not assume it creates a tenant invoice automatically.
5. Choose **Save draft** if the entry is unfinished, or **Save and submit for approval** if ready for independent review.

A draft opens bill detail. Submitting can return you to the page where you started, such as the bill list or maintenance request. Read the confirmation, then open the bill again to verify **Submitted**. Give the approver the bill number and relevant supplier documentation through your normal process; submitting the bill does not itself send the supplier payment.

The approved bill must still be posted. A bookkeeper opens it and selects **Post approved bill** in **LedgerOS Sync**. Confirm **Vendor bill posted to LedgerOS** and review the saved posting status before attempting payment.

### Withdraw or correct a bill before posting

A submitted bill cannot be edited. The submitter can use **Withdraw submission**, or the independent approver can reject it with a reason. Correct the draft and submit it again.

For an approved bill that has never started posting, the authorized submitter or an administrator can select **Withdraw approved bill** and enter the required reason. Correct and resubmit it for a new independent decision. If posting has already been attempted, use the recovery procedure instead; withdrawal is no longer available.

## Approve or reject a vendor bill

**For managers or bookkeepers with approval authorization.** The submitter must be someone else.

1. On Home select **Review bill approvals**, or open **Vendor payables → Approval queue**.
2. Find the vendor, amount, property, and submitting user, then select **Review**.
3. Compare **Bill information**, notes, and the supplier documentation. Review the attribution and amount before deciding.
4. Under **Independent review**, enter a reason when rejecting; add a note to an approval when appropriate.
5. Select **Approve bill** or **Reject bill**.
6. Confirm the resulting status and entry in **Approval history**.

An empty queue can mean there are no bills independently reviewable by you. Bills you submitted are excluded. Approval does not post the bill or pay the vendor; hand the approved bill number back to the bookkeeper responsible for posting/payment.

## Pay an approved bill

**For managers or bookkeepers with payment authorization.** This procedure records an externally executed payment.

1. Open **Vendor payables** and select **View** for the bill.
2. Confirm it is approved and posted. Review **Payment status**, **Amount paid**, **Credits applied**, and **Balance due**. If it says **Unavailable** or **Needs review**, resolve that condition before starting another payment.
3. Select **Pay bill**.
4. Review the payment date, amount, method, funding account, and applicable memo/check details. The amount starts at the current balance; reduce it for a partial payment.
5. Select **Post payment** once the details reflect the payment made outside PropertyLedger.
6. On returning to the bill, confirm **Payment posted to LedgerOS** and the refreshed payment status/balance.

For example, a 100 bill paid by 40 should show 60 due, unless an applied credit or other confirmed settlement also affects the balance. The supplier invoice number is different from the application's bill number; retain both in your records.

If the form says **Payment could not be completed**, read the errors, correct the indicated fields, and submit the same form. If a payment has been saved but not confirmed, return to its bill and use **Retry payment** under **Payments awaiting confirmation**. Do not start another **Pay bill** transaction to recover that payment. If the problem persists, give the administrator the bill number, payment number, and exact error.

Use **Payment status → Filter** on the bill list to narrow the list. **Clear filter** restores all bills. The **Maintenance Expense Summary — all bills** above that list remains a summary of all bills even when the list is filtered; do not read it as the filtered subtotal.

## Review reports and owner statements

### Run a report

1. Select **Reports** in the sidebar.
2. Choose the relevant report under **PropertyLedger reports** or **LedgerOS reports**.
3. Set the property, tenant, dates, or as-of date where provided. A blank property filter can include all available properties.
4. Select **Run report**.
5. Check the displayed period and scope before interpreting or distributing the results.

Use **Rent roll** for lease/occupancy information, **Tenant ledger** for tenant activity, **Delinquency** for outstanding charges, and **Property income / expense** for posted charge/bill activity. **LedgerOS reports** provide the accounting-system reports, including trial balance, P&L, balance sheet, and bank/reconciliation information.

Some current report results need additional reconciliation:

- Tenant-ledger running balances can disagree with the displayed chronological row order. Check the underlying charges and receipts when using the progression of balances.
- Delinquency can differ from the tenant ledger when part of a receipt has posted but the entire receipt has not finalized. Its as-of date also does not reliably exclude later payment applications. Verify the original receipt before contacting a tenant for another payment.
- The deposit report's ending amount reflects selected-period activity; it is not a verified lifetime liability balance.
- Locally archived records and bills carrying overlapping maintenance/expense categories can produce differences in owner-statement totals. Resolve those differences against the source bills and LedgerOS before sending a statement.

Report unavailability is not a zero balance. General report CSV export is not provided; owner-statement export is available as described next.

### Prepare an owner statement

1. Select **Owner statements** in the sidebar.
2. Choose the owner and their property.
3. Choose **Month**, **Quarter**, **Year**, or **Custom range**. Enter a date in the required period as **Period start**; for a custom range enter both start and end dates.
4. Select **Preview statement**.
5. Confirm the owner, property, displayed dates, and totals. Reconcile the source records, including the limitations above.
6. Select **Export CSV** when ready. The browser downloads a file that you can open in your spreadsheet application and save in your normal statement folder.

The statement's **Net summary** combines invoice collections, expenses, owner contributions, and distributions. Deposit activity and Other allocations are shown separately; they are outside that net. **Pending sync** under Reports can help identify unposted owner activity and management-fee bills, but is not a list of every unfinished item in PropertyLedger.

### View banking information

Bookkeepers can open **Banking** in the sidebar to review bank-account and reconciliation summaries from LedgerOS. This is a viewing screen; it does not import bank statements, match transactions, or complete reconciliation. Use your authorized LedgerOS process for those tasks.

## Record other financial activity

### Record a debt service payment

**For bookkeepers.** Have the actual payment, principal/interest split, lender, property, and configured account names ready. Ask the administrator if a required account is missing.

1. Select **Debt service**, then **Add payment**.
2. Enter the property, lender, payment date, total, principal, interest, funding account, liability account, interest expense account, and memo.
3. Confirm that principal plus interest equals the total and the account names are correct.
4. Select **Save payment** only when ready: this action can immediately attempt posting to LedgerOS.
5. Open the saved payment and verify its result under **LedgerOS Sync**. Use **Sync payment** on that same payment to retry after resolving a failure.

Paying a vendor bill by credit card is supported through **Pay bill**. A later card payoff is separate; the current application does not provide a clear standalone payoff workflow. Ask your administrator for the approved procedure rather than paying the vendor bill again.

### Record an owner contribution or distribution

**For bookkeepers.** Select **Reports → Owner activity → Add owner activity**, or open **Owner activity** from the sidebar. Enter owner, property, event type/date, amount, payment account, description, and notes.

Choose **Draft** to retain the entry without posting. Choosing **Ready to sync** and saving attempts posting. If the form does not show a clearly labelled save button, stop and ask your administrator to help with the entry rather than guessing which control to use. Reopen the saved record and check both **Status** and **Sync** before relying on it in a statement. If it fails, retain that record and ask the administrator to resolve it; there is no separate retry button on owner-activity detail. Do not use **Archive** to reverse a posted contribution or distribution.

## Correct mistakes and recover unfinished work

### Decide whether the record is still editable

For an unposted draft, open the same record with **Edit**, correct it, and save. A submitted vendor bill first needs withdrawal or rejection. Once posting has been attempted, some fields lock even if you saw an error; the external accounting transaction may already exist.

For a posted or uncertain transaction, retain the record and ask the responsible administrator/bookkeeper to arrange a supported correction or reconciliation. Do not delete it in the administration screen or use **Archive selected** as an accounting reversal. Archiving a tenant can cancel its leases, so do not use it merely to hide a record from a list.

### If LedgerOS is unavailable

Return to **Home** and read the current connection message. A connected message on another page can reflect an earlier check. You can continue local maintenance work and save receipt/bill drafts, but posting and payments need a working connection. After recovery, open the existing record and retry its posting action; there is no automatic offline posting queue.

### If an action is missing or blocked

| What you see | What to do |
| --- | --- |
| No create/edit controls, or an access-denied message | Ask the administrator to check your role. For approval/payment, also check the separate authorization. |
| No lease, tenant, vendor, or property available to select | Ask the manager/bookkeeper responsible for that record to check that it exists and is active where required. |
| No **Approve bill** action | Check that the bill is Submitted, you have approval authority, and someone else submitted it. |
| No **Pay bill** action | Check approval, successful posting, current balance, payment authority, and the explanation under **Payment unavailable**. |
| Receipt cannot post | Check that the full amount is allocated and any deposit lease/Other account is valid. Read the component error before retrying. |
| **Unknown customer** | Ask a manager/administrator to provision the tenant, then retry the original invoice. |
| Deposit says **Needs review** | Review existing receipt/event activity with the responsible bookkeeper; do not record additional money to clear the message. |
| Connection, period, mapping, or account error | Send the exact message to the administrator; keep the saved record for recovery. |

When asking for help, provide the screen name, tenant/vendor/property, record number, date/amount, the action selected, and the exact message. Say whether the receipt or payment already happened outside the application. Keep the record in place so the administrator can follow its history.

When you finish work on a shared workstation, select **Logout** in the header.
