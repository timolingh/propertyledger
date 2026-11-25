# PropertyLedger product specification

**Document revision:** 1.2 · **Reviewed:** November 24, 2026 · **Owner:** Product owner  
**Code baseline:** `c395ef8ed2c629d28991dfe8fa3a3e233a666357` · **Repository:** [timolingh/propertyledger](https://github.com/timolingh/propertyledger)  
**Purpose:** A self-contained statement of desired product functionality, current code behavior, and the gaps between them. No other document is needed to interpret these requirements.

Sections 3–7 define the product contract and its supported boundaries. Section 2 identifies where current code differs from that contract; section 8 defines acceptance checks and points to the relevant code/tests. Issue links identify work items but do not replace the desired behavior described here. Implemented behavior does not become the requirement merely because it exists in code.

## Contents

1. [Product purpose and operating scope](#1-product-purpose-and-operating-scope)
2. [Desired functionality and current gaps](#2-desired-functionality-and-current-gaps)
3. [Records and permissions](#3-records-and-permissions)
4. [Setup and portfolio onboarding](#4-setup-and-portfolio-onboarding)
5. [Daily workflows](#5-daily-workflows)
6. [Reports and statements](#6-reports-and-statements)
7. [Accounting, integration, and outage rules](#7-accounting-integration-and-outage-rules)
8. [Acceptance checks and code locations](#8-acceptance-checks-and-code-locations)

## 1. Product purpose and operating scope

PropertyLedger helps property managers and bookkeepers maintain a rental portfolio, record externally executed financial activity, follow maintenance work, and produce property-context reports. Its shared Home starts three jobs: **Collect Rent / Deposit**, **Get Billed & Pay Vendors**, and **Log Maintenance Request**. Existing record, setup, banking, audit, and reporting screens remain reachable through the sidebar.

PropertyLedger owns properties, units, owners, tenants, leases, maintenance, local approvals, receipt allocations, property attribution, and links to accounting results. **LedgerOS is the accounting system of record** for posted invoices, bills, payments, journals, balances, periods, and accounting reports. PropertyLedger uses its HTTP adapter; it must not import LedgerOS models or write to the LedgerOS database.

The supported operating model is one configured LedgerOS entity/books selection for the installation, one primary owner per property, monthly base rent, and decimal money with two places. There is no per-record currency conversion or separate owner-books routing. Dates are explicit business dates; automatic “today” values use the application's timezone, currently UTC in [settings](../propertyledger/settings.py), rather than the workstation timezone.

Users record money received or paid outside the application. The application does not debit tenant accounts, send ACH, process cards, or deliver vendor funds. Tenant and owner portals, fractional ownership, multi-entity routing, bank feeds, automatic late fees, automatic management-fee calculation, general offline posting, check printing, and jurisdiction-specific deposit compliance are outside the current product scope. A new combined refund/reversal or multi-lease deposit allocation workflow requires a separate design.

## 2. Desired functionality and current gaps

The requirements in sections 3–7 apply unless a supported boundary is explicitly stated. The table below records known differences; absence from the table is not proof that every path has been tested. Unresolved design choices are identified rather than silently filled in.

| Area / requirement | Desired functionality | Current code behavior and gap | Work item |
| --- | --- | --- | --- |
| Posted payment history · AP-07, OPS-03 | Posted and attempted payment records, component identities, and accounting references survive individual and bulk admin operations. Corrections use a supported accounting workflow. | Django admin can delete a posted local payment while its sync/journal reference remains. Existing edit protections do not prevent this deletion. | [#30](https://github.com/timolingh/propertyledger/issues/30) |
| Financial readiness · HOME-04, OPS-02 | Every supported financial entry point, including service/admin callers, checks bounded readiness before creating a new posting attempt. Local drafts remain usable. | UI handlers preflight readiness, but direct payment-service and admin calls can attempt posting without consulting that preflight. | [#31](https://github.com/timolingh/propertyledger/issues/31) |
| Global connection status · HOME-06, OPS-02 | All pages distinguish current connection, outage, setup, and permission conditions, with a nearby details link. Old/unknown health must not imply a live connection. | Home probes readiness; other pages can display “LedgerOS connected” from an old recorded healthy result. | [#32](https://github.com/timolingh/propertyledger/issues/32) |
| Maintenance bill details · MAINT-07 | Each linked bill shows approval, posting, payment status, confirmed paid/remaining amounts, and a controlled reconciliation explanation. Unavailable is distinct from zero. | The table shows status and remaining balance but omits paid amounts and reconciliation error explanations. | [#33](https://github.com/timolingh/propertyledger/issues/33) |
| Home payment/maintenance navigation · HOME-03, HOME-08 | “Pay approved bills” opens eligible approved posted payables; queue links describe and retain their intended scope. | The payment action opens all bills; maintenance queue footers say “View all vendor payments.” | [#34](https://github.com/timolingh/propertyledger/issues/34) |
| Maintenance photos · MAINT-01 | Optional staff attachments require private durable storage, access controls, image validation, size limits, metadata removal, and retention rules before upload controls appear. Storage policy and target release remain undecided. | No photo fields, upload controls, or private attachment storage exist. This conditional feature remains unimplemented. | [#35](https://github.com/timolingh/propertyledger/issues/35) |
| Scheduled rent generation · RENT-01 | Generate next month's rent automatically five days before its first day by default, with configurable advance days. Invoice and due dates are that month's first day; retries do not duplicate the lease/month charge. | Generation is manually initiated. Current generated charges use the month's first day as charge date and last day as due date; there is no automatic advance scheduler. | [#27](https://github.com/timolingh/propertyledger/issues/27) |
| Manual rent invoice defaults · RENT-01 | Prefill amount from the selected lease and invoice/due dates from the first day of the current month, allowing review before submission. | The requested combined lease/month prefill behavior is not implemented. | [#28](https://github.com/timolingh/propertyledger/issues/28) |
| Card payoff entry · FIN-02 | Provide an explicit card-payoff workflow distinct from settling a vendor bill, without recognizing bill expense or settling AP again. Detailed entry design remains to be specified. | The accounting path exists, but the user flow is not explicit and the existing model/service path retains bill context. | [#8](https://github.com/timolingh/propertyledger/issues/8) |
| Tenant-ledger running balances · REP-01, REP-03 | Every displayed running balance follows the same chronological order as the displayed entries and reconciles to opening/closing totals. | Entries are sorted after running balances are computed; per-row progression can disagree with displayed chronology. | No issue assigned |
| Delinquency consistency · REP-01, REP-02, REP-03 | An as-of report includes qualifying confirmed applications through the selected date, including confirmed components of an incompletely finalized receipt. It must not imply the same money is owed again. | Payments require succeeded parent finalization as well as application sync, and are not cut off by the as-of payment date. Results can differ from the tenant ledger and are not a historical balance snapshot. | No issue assigned |
| Statement expense/inclusion consistency · REP-03 | Count each eligible bill once in the net expense calculation and explain differences from other property reports. Local archive must never masquerade as an upstream reversal. | Maintenance classification can overlap another expense category, and statement selection does not uniformly exclude local voided records as other reports do. Exact correction/void inclusion semantics need a product decision before implementation. | No issue assigned |

Supported limits are not automatically missing features: one primary owner per property, one deposit lease and one Other account per receipt, read-only banking, and no payment-rail initiation are the intended boundaries. Deposit required/deducted event types have no approved posting treatment; do not infer one from their presence in the model. Owner-viewer access is reporting access, not a scoped owner portal.

## 3. Records and permissions

### 3.1 Core relationships and terminology

| Record | Meaning and relationships |
| --- | --- |
| Owner → Property → Unit | An owner can own multiple properties; each property has one primary owner and multiple units. Unit names are unique within a property. |
| Tenant → Lease | A lease joins one tenant to one unit, with dates, monthly rent, required deposit, and draft/active/ended/cancelled status. A tenant may have multiple leases. |
| Invoice (`TenantCharge`) | A lease-scoped or model-supported property-level charge. Normal invoice entry is lease-led; the lease supplies tenant/property/unit. Generated base rent is unique by lease and billing period. |
| Receipt (`TenantPayment`) | One externally received amount, with invoice applications, optional one-lease deposit allocation, optional Other allocation, and a local finalization summary. |
| Deposit event | A standalone lease/property/unit/tenant event. It must not duplicate deposit money already recorded on a receipt. |
| Vendor → VendorBill → VendorPayment | Bills carry property and optional unit/category context; payments settle specific bills. Operational approval and upstream posting/payment states are separate. |
| MaintenanceRequest → bills | One request can link multiple bills/vendors. A bill belongs to at most one request. Linked payment records remain attached to their bills. |
| Owner activity | A contribution or distribution attributed to the property's primary owner and property. |
| Sync record / audit event | A sync record stores request identity and outcome; an audit event attributes a local action. Neither alone proves every related accounting component posted. |

“Posted” is a business outcome, not one universal enum. Invoices use `synced`; receipts/bills/payments use their own local statuses plus sync results. A confirmed receipt component requires its applicable payment/event and posted-journal evidence. “Unavailable” is a read/readiness condition, never a substitute for zero or paid. Local archive/void is not a LedgerOS reversal.

Sources: [portfolio models](../ledgeros/models.py), [payment and maintenance models](../payments/models.py), [owner activity model](../reports/models.py).

### 3.2 Current application permission matrix

This matrix describes application routes and service capabilities, not every Django admin permission. **Grant** means an independent per-user financial authorization in addition to an active eligible role. Unassigned accounts see Home guidance without workflow data. Inactive users fail role checks. Active Django superusers pass role predicates but still need the applicable financial grant and cannot self-approve bills.

| Action / surface | Admin | Property manager | Bookkeeper | Owner viewer | Read-only viewer |
| --- | --- | --- | --- | --- | --- |
| Shared Home | Yes | Yes | Yes | Yes | Yes |
| Setup, mappings, financial-grant administration | Yes | No | No | No | No |
| Portfolio master-data pages; create/edit/archive; tenant provisioning | Yes | Yes | No | No | No |
| Invoice reporting/detail, vendors, receipts, deposits, bill/payment reads, reports, audit | Yes | Yes | Yes | Yes | Yes |
| Charge dashboard, generate/create/edit/post invoices | Yes | No | Yes | No | No |
| Receipt/deposit entry, allocation, posting | Yes | No | Yes | No | No |
| Vendor/category editing; bill create/edit/submit/post | Yes | No | Yes | No | No |
| Approve/reject a different user's submitted bill | Grant | Grant | Grant | No | No |
| Record/retry eligible bill settlement | Grant | Grant | Grant | No | No |
| Maintenance read | Yes | Yes | Yes | No | Yes |
| Maintenance create/lifecycle; link compatible existing bills | Yes | Yes | Yes | No | No |
| Create a vendor bill from maintenance | Yes | No | Yes | No | No |
| Banking dashboard; debt-service/card-payoff writes; owner-activity writes | Yes | No | Yes | No | No |

The owner-viewer role is **not an owner-scoped portal**: current reporting routes do not infer ownership-based row filtering from that role. Staff status permits entry to Django admin only when other admin checks pass; it does not itself assign a workflow role. Generic admin permissions differ from application routes, and history deletion/readiness gaps remain tracked in §2.

Sources: [role predicates](../ledgeros/roles.py), [route mixins](../ledgeros/permissions.py), [financial grants](../payments/authorization.py), [routes](../ledgeros/urls.py), [payment routes](../payments/urls.py), [report routes](../reports/urls.py).

## 4. Setup and portfolio onboarding

### 4.1 Prepare the intended books

**SETUP-01:** An administrator configures the reachable LedgerOS endpoint/client, environment-held signing secret, optional host-header/bearer settings, and health path. Saved settings hold secret-variable names, not the secret values. Select the intended entity and accounting period separately from the technical connection.

**SETUP-02:** Setup completion requires a successful recorded health check, selected books, valid required account mappings, valid enabled optional mappings, and a successful recorded setup smoke result. The required mapping keys are `operating_bank_account`, `undeposited_funds`, `accounts_receivable`, `accounts_payable`, `rental_income`, `repairs_and_maintenance_expense`, `tenant_security_deposits_liability`, `owner_contributions_equity`, and `owner_distributions_equity`. Optional financing/card keys are `credit_card_liability`, `mortgage_or_loan_liability`, `interest_expense`, and `principal_payment_mapping`. Verify actual upstream accounts and periods as well as local labels/types; local setup completeness is not proof a later transaction can post.

**SETUP-03:** Assign active workflow roles and explicit approval/payment grants before financial use. Bill submitters need a different authorized approver. Migration creates no automatic production financial grants. The global payment workflow settings also retain the legacy invoice-type allocation priority used by older receipts; reviewed receipts use the waterfall in §5.3.

The administrator must be able to configure the application against an independently running LedgerOS endpoint and complete Setup at `/` without inserting synthetic transactions or deleting bookkeeping data. Current tooling uses `make up`, `make migrate`, a containerized `createsuperuser` command, and `make smoke`; the smoke command also starts/builds services and runs migrations/bootstrap. The sample-data development bootstrap is not the intended production onboarding flow. Configuration keys are defined in [.env.example](../.env.example); exact tool behavior is in the [Makefile](../Makefile).

### 4.2 Establish the portfolio

**CORE-01:** Create owners, properties, units, tenants, and leases in dependency order. Record dates, rent, deposit requirement, and lease status; archive/inactivate master data through supported actions rather than deleting accounting history. A lease or deposit requirement does not record money received or post a journal.

**CORE-02:** Property and tenant creation provision LedgerOS customers through their existing creation paths; failed provisioning rolls back that local creation. Editing an existing tenant does not automatically provision or update its customer. Tenant status badges describe recorded evidence, not a live upstream lookup.

**CORE-03:** Admins/managers can explicitly review and provision an existing tenant using its stable `tenant-<id>` code, name, and AR mapping. GET only reviews; a signed, CSRF-protected POST creates a missing customer or verifies an exact active match. Conflicts do not overwrite or reactivate a different customer. Retry the same reviewed request after a timeout. Recovery does not automatically retry an invoice; post the original invoice explicitly after provisioning. The strict LedgerOS customer endpoint must be deployed; there is no upsert fallback for this action.

**CORE-04:** Normal invoice entry infers attribution from the lease. On applicable maintenance, receipt, deposit, and bill forms, unit/tenant selections suggest related property/unit values. Multiple active units require an explicit choice. Server validation remains authoritative; existing saved values do not change merely because a page is viewed.

Sources: [setup and portfolio views](../ledgeros/views.py), [provisioning and rent services](../ledgeros/services.py), [relationship helpers](../ledgeros/form_relationships.py).

## 5. Daily workflows

### 5.1 Home and navigation

Login leads to `/home/` for all authenticated roles; `/` remains administrator Setup. The persistent sidebar collapses on desktop and becomes a mobile menu. Three recognizable workflow cards remain present; actions reflect the destination's permission rules. Available read actions must remain reachable when writes are unavailable.

| Requirement | Required behavior / current qualification |
| --- | --- |
| HOME-01 | One authenticated workflow Home; no role-dependent home redirects. |
| HOME-02 | Responsive sidebar with equivalent desktop/mobile reachability; preserve existing named routes and deep links. |
| HOME-03 | Three equally prominent cards with real actions and permission-filtered queues. Current queues show receipts awaiting finalization, attempted payments awaiting confirmation, approvals excluding self-approval, active maintenance, and maintenance awaiting a bill; five rows maximum with full local counts. Eligible-payable navigation and maintenance footer labels remain a known gap (#34). |
| HOME-04 | Enforce destination capabilities on views, services, admin, and supported write paths. Service/admin readiness consistency remains a known gap (#31); financial grants are independently checked. |
| HOME-05 | Read roles receive permitted detail/report links and cannot use financial write controls. Portfolio/maintenance access follows §3.2. |
| HOME-06 | Setup and connection status remain visible without replacing the workflows. Home probes current readiness; global freshness remains a known gap (#32). |
| HOME-07 | Home GET creates no setup rows, requests no financial posting, and does not retry or reconcile operations. Home POST is unsupported. |
| HOME-08 | Keyboard labels, active navigation, skip link, focus handling, empty/error states, and mobile Escape/focus return are required. Desktop collapse is remembered; mobile navigation remains expanded without JavaScript. |

Local queue counts are workflow counts, not balances or a claim that every row is assigned to the current user. Read/write capability is evaluated independently of the heading “My Work Queues.”

Source: [Home composition](../propertyledger/workflows.py), [Home template](../ledgeros/templates/ledgeros/workflow_home.html), [navigation](../ledgeros/navigation.py).

### 5.2 Invoices and monthly rent

Admins/bookkeepers generate a selected month's base rent from active leases or enter a manual invoice. Generation prorates occupied days for mid-month lease dates and prevents a second base-rent charge for the same lease/period. Current generated invoices use the month's first day as charge date and last day as due date. Automatic advance scheduling and alternate manual defaults are planned work, not existing behavior (#27, #28).

The invoice UI uses `TenantCharge`. Its local path is draft → approved → sync pending → synced, or sync failed; voided is a local archive state. **Approve and post to LedgerOS** on detail/edit uses the saved invoice, not unsaved form values. After confirmed posting, the detail offers receipt entry. Bulk approval retains the same service path. Failed posting is recovered on that same invoice. A missing-customer failure follows §4.2.

**RENT-01:** Preserve lease/period generation uniqueness, invoice selection/approval, property attribution, and stable invoice posting identity. Synced invoice edits are restricted by the current form to due date/description; these local edits are not a promise that an existing upstream invoice is updated. A local archive must never be presented as an accounting reversal.

Sources: [rent generation and invoice services](../ledgeros/services.py), [charge views](../ledgeros/views.py), [charge model/form](../ledgeros/forms.py).

### 5.3 Recording and posting a receipt

Start from Home's receipt action or **Record receipt and review allocation** on an invoice. Enter the entire externally received amount once. Review the waterfall **Open invoices → Deposit → Other** on that form, then **Save receipt for review**. On the saved receipt choose **Post receipt to LedgerOS**; eligible existing receipts also offer **Save and post receipt**.

Open invoices include invoiced late fees and are allocated oldest due date first. Zero skips a category. A positive deposit requires one matching lease and available deposit capacity; multiple eligible leases require selection. Positive Other requires one credited account. Drafts may retain unapplied money, but posting requires complete allocation. Review existing unused funds on the original receipt; do not enter the payment again. Older unreviewed receipts retain their legacy allocation controls, but these are not prerequisite steps for new reviewed receipts.

| Requirement | Contract |
| --- | --- |
| RENT-02 | Record externally executed receipts only; no payment processor or funds-transfer initiation. |
| RENT-03 | Zero or more invoice applications, zero or one deposit allocation to one matching tenant/property lease, and zero or one Other allocation to one account. Their sum must equal the full receipt before finalization. Multi-lease deposit splitting is outside the release. |
| RENT-04 | Each component posts only its own amount. Invoice components use the payments API; deposit and Other use explicit sync-event journals. The parent finalization is local and never posts Cash again. |
| RENT-05 | Finalization requires confirmed posted evidence for every allocation. Partially successful receipts retain confirmed components without representing the whole receipt as posted rent. Report-specific inclusion rules are in §6. |
| RENT-06 | Persist component identities/frozen requests before attempts; reject changed attempted payloads and reuse keys on retry. Confirmed components are skipped. Older receipts can allocate unused funds after confirmed invoice applications; uncertain attempts must be resolved before changing that split. |
| RENT-07 | Validate the exact invoice/deposit/Other accounting contract against the intended LedgerOS deployment before release or contract changes, including partial failure, accounts/periods, and replay. Local tests alone do not prove live compatibility. |

Other debits configured operating Cash and credits its selected account. It cannot credit the configured receiving Cash, AR, or tenant-deposit control account; use the dedicated allocations for those accounts. LedgerOS validates the account and period. Other is not invoice settlement or rent; it appears separately by account in property reports and owner statements/exports, outside the owner rent/net summary.

**Acceptance example:** A 2,100 receipt allocated 1,500 to invoices, 500 to deposit, and 100 to Other produces aggregate Cash +2,100, AR −1,500, deposit liability +500, and Other-account credit 100. A timeout retry changes neither confirmed journal count nor aggregate amounts. Rent-only, deposit-only, and Other-only receipts use the same component rules. A 2,000 receipt split 1,500 invoices / 500 deposit follows the same accounting rules.

Sources: [receipt form](../payments/receipt_forms.py), [waterfall and Other services](../payments/receipt_services.py), [component posting](../payments/services.py).

### 5.4 Security deposit collection and refunds

The deposit screen compares the lease requirement with confirmed receipts from receipt components and standalone received events. A draft “Received” event contributes zero confirmed collection. Both paths share the lease deposit ceiling; a fresh operation cannot consume capacity already committed or awaiting confirmation. Retrying the original uncertain operation preserves its frozen request and key. Refunds and local voids do not automatically authorize recollection.

**DEP-01:** Show required, confirmed received, and remaining initial collection separately, with source links. Remaining is normally `max(requirement − confirmed receipts, 0)`. Uncertain attempts, journal-less legacy successes, refunds/deductions, and excess collection require explicit review. This projection is not a live deposit-liability balance.

**DEP-02:** Standalone received/refunded events post Cash/liability entries on their event date with posted-journal evidence. Required/deducted event types remain local records without a supported posting contract. Do not claim deposit deductions, legal disposition, or replenishment obligations are implemented merely because those event types exist. Never post a standalone event for money already on a receipt.

Sources: [collection projection](../payments/deposit_activity.py), [shared capacity guard](../payments/deposit_limits.py), [event posting](../payments/services.py).

### 5.5 Vendor bills, approval, and payment

Admins/bookkeepers maintain vendors and explicitly sync/retry their LedgerOS provisioning; vendor save also retains automatic provisioning behavior. Status is the stored result. A vendor must be provisioned before its bill posts. Payment terms are upon receipt, 15, or 30 calendar days; new bill dates default to application “today,” with suggested due dates from terms. Manual overrides persist and later vendor-term changes do not rewrite existing bills. Optional supplier invoice numbers accompany new bill posting and participate in approval materiality.

New bills follow **Draft → Submitted → Approved → explicit LedgerOS posting → eligible settlement**. Rejected/withdrawn bills can be corrected and resubmitted. **Save draft** opens bill detail; **Save and submit for approval** returns to a validated local referring page, with a bill-list or maintenance fallback. Neither action posts automatically.

| Requirement | Contract |
| --- | --- |
| AP-01 | Save/submit/review/approve-or-reject explicitly. Submitted bills cannot be edited. Material approved-field changes invalidate approval; notes excluded from the financial fingerprint do not. |
| AP-02 | An active individually authorized approver must differ from the submitter, even for administrators. Record decision actor/time, submission version, approved fingerprint, and immutable history. |
| AP-03 | Payment grants are independent from approval grants, require an eligible active role, and are checked from current database state. Administrators manage grants but receive neither automatically. |
| AP-04 | New settlement requires an approved, successfully posted bill and a confirmed positive eligible payable balance. Reject voided, fully paid, unavailable, inconsistent, or excessive-payment requests. |
| AP-05 | Start from **Pay bill** on bill detail; bill/vendor are fixed, amount defaults to the current balance, and partial payments are allowed. Preserve signed submission identity, row locking, retries, and bank/card funding treatment. Opening the form posts nothing. |
| AP-06 | Display approval, posting, and payable status independently. Bill reads include payments and vendor credits applied directly in LedgerOS; unallocated journals are not inferred as bill applications. |
| AP-07 | Preserve historical bills/payments and retry identity. A legacy posted bill receives prospective independent approval before a new settlement, without reposting or inventing past approval. Card payoff/debt service are separate flows. History deletion remains a known gap (#30). |

An approved local draft bill with no linked sync record may be withdrawn by its authorized submitter or administrator with a reason. Once posting has started, including failed/uncertain requests, recover the same attempt; do not withdraw it into an editable replacement. Resubmission after valid withdrawal requires fresh independent approval.

After a payment failure, use the saved payment under **Payments awaiting confirmation**. Another currently authorized payer can resume it after the original payer loses authority. A fresh upstream balance of zero must not force replacement of a potentially committed payment. Status can be unpaid, partially paid, paid, not posted, voided, needs review, or unavailable. Legacy generic card journals require explicit existing-journal reconciliation; its command previews by default and apply requires an authorized actor. No replacement journal is permitted to resolve missing evidence.

**Acceptance example:** A 100 bill posts expense +100 / AP +100. A 40 bank payment reduces AP and Cash by 40, leaving 60 due. A 10 vendor credit applied upstream leaves 50 due and remains distinct from cash paid. Repeating the same payment submission creates no extra payment or journal. Approving a bill alone creates no accounting entry.

Sources: [approval services](../payments/approval_services.py), [bill/payment services](../payments/services.py), [existing-journal reconciliation](../payments/management/commands/reconcile_bill_card_payments.py).

### 5.6 Maintenance through vendor billing

Staff enter property, description, category, and priority; unit, tenant, vendor, target date, and nonnegative estimated cost are optional. Property-wide requests need no unit. A selected unit must belong to the property and a selected tenant must have a lease associated with that scope. Origin metadata reserves future integrations; it does not provide a tenant portal or public maintenance API. Photos are absent pending #35.

| Operation | Implemented transition / prerequisite |
| --- | --- |
| Triage → assign → start → verify | Open → Triaged → Assigned → In progress → Verified. Assignment requires a vendor; verification records actor/time. |
| Hold / resume | Triaged, Assigned, or In progress → On hold with reason → the saved prior state. |
| Close | Verified → Closed, with a closure note and either Vendor invoice pending or No external cost. No bill/payment prerequisite. |
| Reopen | Closed → Triaged with reason; preserve prior closure history and linked bills. Reopened is an event, not a separate persisted status. |
| Cancel | Open, Triaged, Assigned, In progress, or On hold → Cancelled with reason. Cancelled requests have no supported reopen action. |

| Requirement | Contract |
| --- | --- |
| MAINT-01 | Validate the fields above. Photo support is conditional planned work, not an available optional field. |
| MAINT-02 | Authorized lifecycle services lock/reload the request, check its submitted version, and record immutable actor-attributed events; stale transitions fail without overwriting history. |
| MAINT-03 | Verified work can close without a bill or payment, including no-cost work; preserve the explicit closure outcome. |
| MAINT-04 | On arrival of a vendor invoice, create/link bills at any maintenance stage, including after closure. |
| MAINT-05 | Support multiple vendors/bills per request and multiple payments per bill; each bill links to at most one request. Multi-request cost splitting is outside scope. |
| MAINT-06 | Creating a bill requires bill-editor authority; managers can link compatible existing bills. Prefill safe context, validate property/unit compatibility, and reuse the original bill on repeat handoff submission. GET creates no bill. |
| MAINT-07 | Operational status is independent of approval/posting/payment. Credits, reversals, bill links, and settlement do not implicitly reopen/close maintenance. Linked-bill paid amounts and reconciliation explanations remain a known display gap (#33). |
| MAINT-08 | Internal staff create requests; preserve origin metadata for future tenant requests without granting tenant access now. |

Maintenance saves remain local during LedgerOS outages and create no invoice, payment, journal, or accounting total. Closed/cancelled records cannot be edited as active work; reopening a closed request preserves the earlier event history.

**Acceptance example:** Link a plumber's 500 bill and painter's 300 bill to one request. Close verified work while those bills remain unpaid; later link another compatible bill without reopening. Each bill's independent approval and payment state remains visible. Reopening with a reason returns to Triaged without deleting the prior closure or bills.

Sources: [lifecycle and handoff services](../payments/maintenance_services.py), [maintenance views](../payments/maintenance_views.py), [linked-bill detail](../payments/templates/payments/maintenance_detail.html).

### 5.7 Debt service and credit-card payoff

**FIN-01:** A manually entered debt-service payment has property/lender context, principal and interest, and a funding account; principal + interest equals total. It posts debit loan liability for principal, debit interest expense, credit operating Cash for total. There is no amortization scheduler or automatic split calculation.

**FIN-02:** Paying a vendor bill by card settles AP and credits card liability through the supported payments API. Paying off that card is a distinct Cash-to-card-liability journal and must not settle the bill or recognize expense again. The model/service path exists, but a clear standalone payoff workflow remains tracked in #8; the legacy path still carries bill context. Card feed imports, statement matching, and printed checks are not provided.

Source: [debt/card services](../payments/services.py).

## 6. Reports and statements

### 6.1 Report definitions and limits

PropertyLedger financial views are local projections of recorded sync evidence. They are not a live full replica of LedgerOS, and generally do not import every upstream-only transaction or reversal. LedgerOS reports provide the authoritative GL view. Local operational reports and previously confirmed history can remain visible during outages; current upstream balances must be unavailable when they cannot be read.

| Report / surface | Source, date basis, and filters | Inclusion / meaning |
| --- | --- | --- |
| Rent roll | Leases, tenants, units; as-of date and optional property | Active leases overlapping the date. Operational rent/occupancy, not posted revenue. |
| Tenant ledger | Confirmed local charges by charge date and receipt invoice components by payment date; period/property/tenant | Opening/closing totals use charges less confirmed invoice applications; deposit/Other are excluded. Components can count before parent finalization. Per-row running balances are computed before final display sorting, so their chronological progression requires reconciliation. |
| Delinquency | Synced nonvoided local charges due on/before as-of date; optional property | Subtracts applications only when application and parent receipt sync succeeded, without cutting payments off at the as-of date. Partial receipts can differ from the tenant ledger, and this is not a historical balance snapshot. Do not collect the money again to resolve a reporting difference. |
| Property income/expense | Synced nonvoided charges and bills by charge/bill date; date range/property | Accrual income less bill expense. Invoice collections are a separate cash memo; confirmed Other allocations appear separately by credited account. This is not a complete property GL or refined cash-basis report. |
| Owner statement | Owner/property, month/quarter/year/custom range; charge/bill/payment/event dates | Base-rent charges, confirmed invoice collections, synced bills, owner activity, and deposit activity; preview and CSV export. Formula and limitations below. |
| Security-deposit ledger | Succeeded standalone events and receipt deposit components by event/payment date; period/property/tenant | Period activity with a running total starting at zero for the selected range. Its “Ending balance” is not a verified lifetime liability balance. Use §5.4 for initial collection readiness. |
| Management-fee / maintenance summaries | Synced vendor bills by bill date; date range/property | Categorized recorded expense. Management fees are manually entered; no percentage calculation or accrual automation. |
| Pending owner sync | Owner contributions/distributions and management-fee bills without succeeded sync, selected owner/property | Explains excluded pending records; it is not a complete pending-work inventory across the product. |
| LedgerOS reports | Signed upstream reads with supported date parameters | Trial balance, P&L, balance sheet, period/tax summary, chart of accounts, invoice/bill/payment status, bank balances, reconciliation status, and audit drilldown rendered in PropertyLedger. Upstream errors remain errors/unavailable. |

**REP-01:** Report definitions must state source, date basis, scope, signs, and sync eligibility. Keep operational counts separate from balances; do not replace upstream failures with zero. Preserve existing report-specific historical handling until an explicit reconciliation change is approved.

**REP-02:** Confirmed receipt invoice components contribute to invoice collection/tenant settlement; deposits and Other remain separate. The shared rent helper retains a whole-receipt fallback for succeeded historical parent-only receipts without reviewed/component evidence. Do not automatically repost, fabricate components, or treat these legacy amounts as proof of a modern allocation.

### 6.2 Owner statements and owner activity

**OWN-01:** Admins/bookkeepers record property-attributed owner contributions/distributions; the owner must match the property's primary owner. Contribution posts debit Cash / credit owner-contribution equity. Distribution posts debit owner-distribution equity / credit Cash. They appear in statement totals after succeeded sync; saving a draft does not post. No automated payout, owner payable subsystem, fee engine, or separate owner books is supplied.

**OWN-02:** Preview/export is selected by owner + property and month, quarter, year, or custom dates; no persisted statement-approval workflow exists. The current net summary is **invoice collections − property expenses − maintenance expenses − management-fee expenses + contributions − distributions**. Refundable deposit activity and Other are separate memo information outside that net. This operational summary is not a bank balance or the LedgerOS P&L.

**REP-03:** Reconcile statement/report totals to source rows and upstream posted evidence before treating them as financial facts. Current owner statements select by sync success and do not uniformly exclude local voided statuses as other reports do; maintenance classification can overlap another expense category when a maintenance category is also assigned. These source-selection limits need explicit review before changing formulas or promising reconciliation; documenting them does not approve an accounting discrepancy. Local archive is not an upstream reversal. General report CSV export and arbitrary report builders are outside scope; owner-statement CSV is implemented.

Sources: [report calculations](../reports/services.py), [report and CSV views](../reports/views.py), [report forms](../reports/forms.py), [report tests](../reports/tests/test_reports_workflow.py).

## 7. Accounting, integration, and outage rules

### 7.1 Financial invariants and known enforcement gaps

| Requirement | Required safeguard / current qualification |
| --- | --- |
| OPS-01 | During LedgerOS outages permit local maintenance and safe receipt/bill drafts. They are not queued offline postings. |
| OPS-02 | Gate financial posting/payment/finalization on bounded readiness; distinguish missing setup, missing configuration, denied credentials, and unavailable service. UI preflights exist, but common service/admin enforcement is incomplete (#31). Global status freshness also remains incomplete (#32). |
| OPS-03 | GET must never create journals. Keep provenance and accounting IDs; redact credentials and sensitive transport data. Confirm posted evidence rather than assuming a sync row proves success. |
| OPS-04 | Approval decisions, grant changes, maintenance transitions, and bill linkage changes record their actor and immutable history. Preserve original actors/attempts during recovery. |

All money mutations must use the applicable domain service and HTTP adapter. LedgerOS validates accounts, periods, and accounting invariants. Use decimal arithmetic and stable economic identities. A timeout may occur after upstream commit: recover the existing operation with its original payload/key rather than inventing a replacement. A partial receipt exposes confirmed components without posting its full amount twice.

Posted/attempted history must not be destructively edited or deleted. Known exception: Django admin can delete a posted local payment (#30). Approved bills and attempted receipt/payment economic fields have existing editing protections; these do not eliminate the deletion gap or certify every historical path. Corrections require an explicit supported accounting workflow, with any missing correction mechanism designed separately.

### 7.2 Integration and banking boundary

**INT-01:** The local public programmatic surface is `GET /api/health/local/`, `GET /api/health/ledgeros/`, and `POST /api/v1/sync-events/`. The sync-event route stores a local envelope with an idempotency key, replay behavior, and mismatch rejection; it does not dispatch a bill/payment/maintenance workflow or itself prove accounting posting. There is no dedicated external-client authentication layer configured for that surface. Treat it as requiring deployment access controls, not as a public financial mutation API. Authenticated application pages are not stable external integration contracts.

**INT-02:** Signed LedgerOS adapter calls preserve client ownership, account mappings, request identity, and returned resource/journal IDs. Deploy required upstream APIs/migrations first: strict customer provisioning, scoped bill balance reads, supported bill/card settlement, and supplier-invoice references. Invoice payment Cash selection is controlled by LedgerOS and must be verified to match the receiving account used for deposit/Other components. Verify the actual deployed contract; local code or health success alone does not establish compatibility or authorization for a particular write.

**BANK-01:** The banking dashboard reads bank-account/reconciliation summaries from LedgerOS. It has no deposit/withdrawal entry, matching, reconciliation completion, statement import, or bank-feed mutation controls. Report-hub bank/reconciliation reads follow reporting roles; the banking dashboard itself requires Admin/Bookkeeper as shown in §3.2.

Sources: [local API views](../ledgeros/views.py), [serializers](../ledgeros/serializers.py), [adapter services](../payments/services.py), [banking view](../payments/views.py), [runtime settings](../propertyledger/settings.py).

## 8. Acceptance checks and code locations

The checks below define expected outcomes. Linked source/test files identify implementation locations; the requirement itself is stated here. Existing tests are not proof that the gaps in §2 are resolved. For each gap, verify the desired behavior and its failure/retry cases before changing its status.

| Requirement IDs | Acceptance check | Relevant code and tests |
| --- | --- | --- |
| SETUP-01, SETUP-02, SETUP-03 | Missing books/mapping/credential/smoke blocks readiness; saving valid setup records smoke; migration silently grants no production financial authority. | [Setup models/services](../ledgeros/models.py), [setup and API tests](../ledgeros/tests/test_models_and_api.py), [management commands](../ledgeros/tests/test_management_commands.py), [grant tests](../payments/tests/test_workflow_authorization.py). |
| CORE-01, CORE-02, CORE-03, CORE-04 | Create the portfolio in dependency order; failed customer provisioning rolls back creation; explicit provisioning rejects conflicts; ambiguous tenant units are not guessed. | [Portfolio views](../ledgeros/views.py), [CRUD tests](../ledgeros/tests/test_models_and_api.py), [record detail](../ledgeros/tests/test_record_details.py), [provisioning](../ledgeros/tests/test_tenant_provisioning.py), [sync badges](../ledgeros/tests/test_tenant_sync_status.py), [autofill](../payments/tests/test_property_autofill.py). |
| HOME-01, HOME-02, HOME-03, HOME-04, HOME-05, HOME-06, HOME-07, HOME-08 | Every role reaches Home; unassigned user gets no sensitive queues; GET makes no writes; viewer POST denied; desktop collapse/mobile focus and Escape work. Verify #31/#32/#34 separately. | [Home composition](../propertyledger/workflows.py), [Home tests](../ledgeros/tests/test_workflow_home.py), [roles/audit](../ledgeros/tests/test_roles_and_audit.py), [logout](../ledgeros/tests/test_logout.py), [browser checker](../scripts/check-workflow-ui.mjs). |
| RENT-01 | Generate the same lease/month twice: one invoice. Check mid-month proration, saved-invoice posting, and retry of the original missing-customer invoice. | [Rent service](../ledgeros/services.py), [model/API tests](../ledgeros/tests/test_models_and_api.py), [invoice actions](../ledgeros/tests/test_invoice_sync_actions.py). |
| RENT-02, RENT-03, RENT-04, RENT-05, RENT-06, RENT-07 | Exercise both Home and invoice receipt entry; post rent-only, deposit-only, mixed, and Other-only receipts. Verify the §5.3 2,100 example, zero overrides, failed component recovery, unchanged replay IDs/journal counts, and one-lease selection. Live LedgerOS proof remains separate. | [Receipt services](../payments/receipt_services.py), [waterfall tests](../payments/tests/test_receipt_waterfall.py), [mixed receipts](../payments/tests/test_mixed_receipts.py), [payment workflow](../payments/tests/test_payments_workflow.py). |
| DEP-01, DEP-02 | Lease requires 1,450; receipt confirms 500 deposit: remaining initial collection 950. Draft event counts zero; uncertain prior attempt blocks a new deposit. Concurrent receipt/standalone paths share the ceiling. Required/deducted events cannot post. | [Projection/guard](../payments/deposit_activity.py), [collection visibility](../payments/tests/test_receipt_deposit_visibility.py), [shared limits](../payments/tests/test_deposit_limits.py), [posting tests](../payments/tests/test_payments_workflow.py). |
| AP-01, AP-02, AP-03, AP-04, AP-05, AP-06, AP-07 | Reject self-approval and ungranted payer; material edits require reapproval; withdraw only before attempts. Post/pay a 100 bill partially, account for applied credit, retry after timeout or grant revocation, and preserve legacy journals. Test admin history protection when #30 is implemented. | [Approval services](../payments/approval_services.py), [approval tests](../payments/tests/test_bill_approval.py), [grants](../payments/tests/test_workflow_authorization.py), [payment flow](../payments/tests/test_bill_payment_flow.py), [bill balances](../payments/tests/test_bill_payment_status.py), [defaults](../payments/tests/test_vendor_bill_defaults.py), [navigation](../payments/tests/test_bill_submission_navigation.py), [CSRF](../payments/tests/test_bill_csrf.py), [vendor sync](../payments/tests/test_vendor_sync_ui.py). |
| MAINT-01, MAINT-02, MAINT-03, MAINT-04, MAINT-05, MAINT-06, MAINT-07, MAINT-08 | Exercise required/scope fields, stale versions, role denials, hold/resume, reasoned cancellation, no-cost closure, two linked vendor bills, later bill after closure, and reopening with preserved history. Repeat handoff submission: same bill. No operational action posts accounting. | [Maintenance services](../payments/maintenance_services.py), [lifecycle tests](../payments/tests/test_maintenance_workflow.py), [handoff tests](../payments/tests/test_maintenance_billing.py). #33/#35 remain gaps. |
| FIN-01, FIN-02 | Principal 80 + interest 20 posts Cash −100, liability −80, interest expense +20. Card bill settlement and card payoff affect separate liabilities/Cash without recognizing expense or settling AP twice. | [Financial services](../payments/services.py), [payment workflow tests](../payments/tests/test_payments_workflow.py), [bill status tests](../payments/tests/test_bill_payment_status.py). #8 tracks payoff UX. |
| OWN-01, OWN-02, REP-01, REP-02, REP-03 | Attribute activity to the property's owner; compare preview/export and source sums. Separate deposit/Other from rent/net; include confirmed partial components where specified and verify chronological running balances, as-of applications, unique expense inclusion, and explicit void/reversal treatment against the desired behavior in §2. | [Report services](../reports/services.py), [report workflow tests](../reports/tests/test_reports_workflow.py), [Other export tests](../payments/tests/test_receipt_waterfall.py). Report gaps in §2 require additional regression coverage. |
| OPS-01, OPS-02, OPS-03, OPS-04 | Stop LedgerOS: local drafts/maintenance save; posting preflight blocks without a new attempt. Restore it and retry the original IDs. Exercise service/admin as well as UI; reproduce/fix #30–32 explicitly. | [Readiness](../ledgeros/services.py), [outage tests](../payments/tests/test_workflow_outages.py), [health](../ledgeros/tests/test_health.py), [grant/audit tests](../payments/tests/test_workflow_authorization.py). |
| INT-01, INT-02, BANK-01 | Replay same event/key successfully; reject different payload under the same key. Confirm local metadata is not posting. Verify signed reads, clear upstream errors, and no banking mutations. | [API tests](../ledgeros/tests/test_models_and_api.py), [signing/idempotency](../ledgeros/tests/test_signing_and_idempotency.py), [banking tests](../payments/tests/test_banking_visibility.py), [report reads](../reports/tests/test_reports_workflow.py). |

For financial changes, state the expected outbound request, journals, balances, tenant/owner/property report effects, and retry outcome before implementation. Preserve existing enum values and identities; document schema changes and legacy handling rather than silently redefining them. Unresolved access, data-retention, classification, or formula semantics must be decided explicitly rather than inferred from current code.
