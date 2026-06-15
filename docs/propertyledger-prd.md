# PRD — PropertyLedger

## Draft status

This is a review draft. It is not final implementation scope until reviewed and approved.

## 1. Product overview

### 1.1 Product name

Product name: **PropertyLedger**.

Subtitle: **Real Estate Accounting Client for LedgerOS**.

### 1.2 Product description

The product is an accounting-first real estate management application built on top of LedgerOS. It gives property managers and bookkeepers a practical web app for property-level accounting workflows while preserving LedgerOS as the accounting system of record.

The application starts with real estate accounting workflows:

- properties, units, owners, tenants, and leases;
- rent-roll and recurring base rent generation;
- manual tenant charges;
- tenant receivables and payments;
- vendor bills and maintenance expense tracking;
- manual management-fee expense tracking;
- owner statements;
- bank and reconciliation workflows exposed through controlled UI actions;
- PropertyLedger reports plus LedgerOS accounting reports;
- documented API integration for sophisticated users and agent-built connectors.

The product may later expand into broader property-management workflows such as tenant portals, online rent collection, maintenance work orders, document management, leasing workflows, and automated bank feeds, and check writing after the reserved post-MVP module is implemented.

## 2. Product goals

1. Give a property manager a safe, practical accounting workflow without requiring direct use of raw accounting tables.
2. Let a non-technical bookkeeper enter real estate accounting activity through a guided web app.
3. Let sophisticated users or agent-built connectors integrate through documented APIs.
4. Preserve LedgerOS accounting invariants: posted records are immutable, reversals are explicit, periods control posting, and state-changing accounting work goes through services/API contracts.
5. Keep property-management domain logic separate from LedgerOS-specific accounting implementation details.
6. Produce property-manager-friendly reports: rent roll, tenant ledger, delinquency, owner statements, security deposit ledger, management-fee expense summary, maintenance expense summary, and property income/expense.

## 3. Non-goals for MVP

The MVP is not a full property-management platform. The following are deferred:

- tenant portal;
- online rent collection;
- payment processor integrations;
- automated bank-feed ingestion;
- full maintenance work-order system;
- tenant-submitted maintenance requests;
- owner portal;
- automated owner payable/distribution subsystem;
- automated management-fee calculation;
- multi-entity owner books;
- jurisdiction-specific security deposit compliance;
- statutory deposit letters;
- automated sales-tax or local-tax workflows;
- full fine-grained permission matrix;
- QuickBooks/Xero connectors.

## 4. Target users and personas

### 4.1 Primary customer

The first target customer is a **property manager managing units on behalf of owners**.

This user needs:

- property-level accounting;
- tenant ledgers;
- owner statements;
- manual management-fee expense handling;
- vendor bills and maintenance expense visibility;
- bank/reconciliation visibility;
- auditability and safe correction workflows.

### 4.2 Personas

| Persona | Description | Primary needs |
|---|---|---|
| Property manager | Manages properties, owners, tenants, leases, rent activity, and operations | rent roll, tenant balances, owner statements, property performance |
| Bookkeeper | Enters charges, bills, payments, bank activity, and runs reports | safe data-entry UI, clear statuses, reconciliation workflows, accounting reports |
| Sophisticated/API user | Wants to connect external systems or agent-built clients | documented API, HMAC signing, idempotency, event/resource contract |
| Owner viewer | Future role for owners to view statements and reports | owner statement access; portal deferred in MVP |
| Admin | Configures users, properties, accounts, mappings, and LedgerOS connection | setup wizard, permissions, account mappings, smoke tests |

## 5. Product scope

### 5.1 Scope choice

The product is **accounting-first with optional property-management extensions**.

The application starts as a real estate accounting layer:

- property/entity setup;
- rent roll;
- tenant charges and payments;
- vendor bills and expenses;
- owner/property reporting;
- banking/reconciliation visibility and controlled actions;
- LedgerOS sync.

Broader property-management features may be added later.

### 5.2 Portfolio model

MVP uses **one LedgerOS accounting entity** for the property-management business.

Properties, units, tenants, leases, owners, and rent-roll details live in the PropertyLedger application as operational records and reporting dimensions. Owner/property separation is handled through property-level reporting, not separate LedgerOS entities. For MVP, property/unit/lease/owner dimensions are owned by the PropertyLedger application, not LedgerOS.

Deferred: separate owner books, multi-entity routing, consolidated reporting, and inter-entity accounting.

## 6. Architecture overview

The PropertyLedger application must be built as a separate application with its own domain database. LedgerOS remains the accounting backend/system of record.

```text
Users
  |
  v
Real Estate Web App
  |
  v
Real Estate Backend
  |
  +--> Property domain
  |      - properties
  |      - units
  |      - tenants
  |      - leases
  |      - rent roll
  |
  +--> Real estate accounting workflows
  |      - rent charges
  |      - tenant payments
  |      - vendor bills
  |      - owner statements
  |      - maintenance expense tracking
  |
  +--> Accounting adapter boundary
         - LedgerOS adapter
         - HMAC signing
         - idempotency
         - sync status
         |
         v
      LedgerOS Backend
         - invoices
         - bills
         - payments
         - credits/refunds
         - banking/reconciliation
         - reports
         - audit trail
```

## 7. LedgerOS relationship

The product is **LedgerOS-first, with a clean connector boundary**.

MVP requires LedgerOS. However, LedgerOS-specific behavior must be isolated behind an accounting adapter boundary so property-domain logic does not directly depend on LedgerOS tables, models, or implementation details.

Required boundary:

```text
Real estate domain
  -> Accounting adapter interface
  -> LedgerOS adapter implementation
  -> LedgerOS API/services
```

The PropertyLedger application may configure LedgerOS through controlled onboarding/configuration flows, but it must not bypass LedgerOS services or mutate LedgerOS internals directly.

For MVP, property/unit/lease/owner dimensions are owned by the PropertyLedger application, not LedgerOS. The PropertyLedger app must store a sync mapping between each local real estate accounting object and the resulting LedgerOS resource IDs.

This allows the PropertyLedger app to produce property-level and unit-level reports while LedgerOS remains the accounting system of record for posted accounting facts. LedgerOS-native dimensions may be added later if direct LedgerOS-side property/unit reporting becomes necessary.

## 8. Accounting model

### 8.1 Accounting basis

The MVP uses **accrual-style operational workflows** with cash-basis reporting deferred.

Supported in MVP:

- rent charges create tenant receivables;
- vendor bills create payables;
- tenant payments apply against open receivables;
- vendor payments apply against open payables;
- reports should expose real estate operating views and LedgerOS accounting reports.

Deferred:

- refined cash-basis reporting beyond LedgerOS current semantics;
- tax-oriented cash reporting package;
- cash-basis owner statements.

### 8.2 LedgerOS invariants inherited by the app

The PropertyLedger app must preserve these rules:

- state-changing accounting operations must go through LedgerOS APIs/services;
- posted accounting facts are immutable;
- corrections use reversal, credit, refund, adjustment, or explicit workflow actions;
- posting is blocked in closed or locked periods;
- journal entries must balance;
- draft/unposted activity must not affect financial reports;
- audit-relevant successful actions must be logged;
- idempotent API writes must not duplicate accounting records.

## 9. Functional requirements

### 9.1 Setup and onboarding

The app must provide a guided setup flow for administrators.

Required setup steps:

1. Connect to a LedgerOS instance.
2. Validate LedgerOS health and API configuration.
3. Configure one LedgerOS entity for the property-management business.
4. Import or confirm chart of accounts.
5. Create or select the first accounting period.
6. Configure account mappings.
7. Create default bank accounts or map existing LedgerOS bank accounts.
8. Configure optional debt-service account mappings.
9. Configure optional credit-card liability account mappings.
10. Run a smoke-test transaction.

Required real estate account mappings:

| Real estate concept | LedgerOS account type |
|---|---|
| Operating bank account | Asset / cash |
| Undeposited funds | Asset / clearing |
| Accounts receivable | Asset / AR |
| Accounts payable | Liability / AP |
| Rental income | Revenue |
| Late fee income | Revenue |
| Management fee expense | Expense |
| Repairs and maintenance | Expense |
| Tenant security deposits | Liability |
| Mortgage / loan payable | Long-term liability |
| Interest expense | Expense |
| Credit card payable | Liability |
| Owner distributions/contributions | Equity accounts for MVP treatment |

Setup/onboarding must include optional real estate financing and credit-card account mappings. Debt-service MVP support includes manual principal/interest split tracking against a long-term liability account and interest expense account. Automated amortization schedules are deferred.

Credit-card MVP support includes credit-card liability accounts, property/unit expense attribution, and credit-card payoff workflows. Automated card-feed ingestion and card statement reconciliation are deferred.

### 9.2 Properties, units, and owners

The app must support:

- create/edit/archive property;
- create/edit/archive unit;
- associate units with properties;
- create owner records;
- associate owners with properties;
- property-level reporting dimensions;
- owner statement grouping.

MVP uses a simple ownership model: one primary owner per property. Fractional ownership percentages and multiple-owner allocation are deferred.

### 9.3 Tenants and leases

The app must support:

- tenant records;
- lease records;
- lease start/end dates;
- unit assignment;
- base monthly rent amount;
- security deposit required;
- lease status: draft, active, ended, cancelled;
- tenant balance visibility;
- tenant ledger view.

### 9.4 Rent and tenant charges

The MVP uses a hybrid charge model:

- lease-based recurring base rent generation;
- manual one-off tenant charges.

Supported charge types:

- base monthly rent;
- manual repair chargeback;
- manual utility reimbursement;
- manual late fee;
- manual parking/storage fee;
- manual deposit adjustment.

Rent-generation rules:

- generated rent charge must reference property, unit, tenant, lease, and billing period;
- generated charge must be idempotent for the same lease and billing period;
- generated charge must sync to LedgerOS as an invoice or invoice line;
- duplicate rent invoices for the same lease/month must be prevented unless explicitly overridden.

### 9.5 Tenant payments

MVP supports manual payment recording.

Required behavior:

- record tenant payment received;
- apply payment to open tenant charges/invoices;
- support partial payment;
- support overpayment/credit where LedgerOS supports it;
- show tenant payment history;
- sync payment event to LedgerOS;
- store LedgerOS resource IDs and sync status.

Deferred:

- online rent collection;
- ACH/credit-card processing;
- tenant payment portal;
- failed-payment workflow;
- processor fee automation;
- payment webhooks;
- automatic bank-feed deposit matching.

### 9.6 Security deposits

MVP supports simple liability tracking plus manual deduction/refund workflow.

Supported:

- deposit required on lease;
- deposit received from tenant;
- deposit held as liability;
- tenant-level deposit balance;
- manual deduction at move-out;
- manual refund;
- LedgerOS sync to liability account treatment.

Deferred:

- jurisdiction-specific deposit rules;
- automated interest calculation;
- statutory deposit notices;
- move-out inspection workflow;
- legally formatted deposit disposition letters.

### 9.7 Vendor bills and maintenance expenses

The app must support vendor bills and accounting-relevant maintenance tracking.

Supported:

- create vendor;
- create vendor bill;
- associate bill with property and optional unit;
- tag bill with maintenance category;
- add repair notes;
- mark whether expense is tenant-chargeable;
- sync bill to LedgerOS;
- support vendor payments by credit card by clearing accounts payable and increasing the selected credit-card liability account;
- associate credit-card-paid expenses with property, optional unit, and maintenance/category context;
- support credit-card payoff from a bank account;
- support manual debt-service payment entry with principal and interest split;
- include maintenance expenses on property and owner reports.

Deferred:

- full work-order lifecycle;
- tenant-submitted maintenance requests;
- photos;
- vendor dispatch;
- maintenance approval workflows;
- completion inspection.

### 9.8 Management fees

Automated management-fee calculation is deferred from MVP.

The MVP does not calculate percentage-based, flat monthly, tiered, or owner-specific management fees. If a management fee must be recorded, the bookkeeper records it manually as a property-level expense using the normal vendor bill, expense, or journal workflow.

The amount may appear on owner statements and property income/expense reports as a management-fee expense category, but the system does not compute or accrue it automatically.

Deferred:

- percentage-of-rent management-fee calculation;
- flat monthly management-fee automation;
- tiered fees;
- vacancy fees;
- leasing commissions;
- maintenance markup;
- complex owner-specific fee schedules.

### 9.9 Owner statements

MVP supports owner statements but defers a full owner payable/distribution subsystem.

Owner statement must show:

- property;
- statement period;
- rent charged;
- rent collected;
- property expenses;
- maintenance expenses;
- manual management-fee expenses;
- owner contributions, if manually recorded;
- owner distributions, if manually recorded;
- net amount summary or ending owner/property balance.

For the one-entity MVP, owner contributions and distributions are supported as manually recorded owner/property activity. The default MVP treatment is equity-style:

- owner contribution: debit cash, credit owner contribution/equity account;
- owner distribution: debit owner distribution/retained earnings account, credit cash.

The PropertyLedger app must store the owner and property attribution for each contribution/distribution so owner statements can show the activity. The MVP does not implement a full owner-payable subsystem, automated payout calculation, or separate owner equity ledgers. If liability-style owner payable accounting is required later, it should be introduced as a separate enhancement.

Deferred:

- automated owner payable calculation;
- payout approval workflow;
- ACH owner distributions;
- owner portal;
- separate owner LedgerOS entities.

### 9.10 Banking and reconciliation

MVP supports guided banking actions, but not automated bank ingestion.

Supported:

- view bank accounts;
- view bank balances;
- record deposits through controlled LedgerOS APIs;
- record withdrawals through controlled LedgerOS APIs;
- show reconciliation status;
- show unmatched/unreconciled activity.

Because the PropertyLedger app is a separate application, any LedgerOS banking or reconciliation workflow exposed in the real estate UI must be available through a controlled LedgerOS API. The PropertyLedger app must not call LedgerOS internals or rely on Django Admin workflows.

Full reconciliation execution may be phased: creating reconciliation sessions, matching/unmatching items, and completing reconciliation can be near-term post-MVP if not already exposed through LedgerOS APIs.

Check writing is deferred from MVP implementation, but the MVP data model and vendor-payment workflow must reserve a drop-in path for it. Vendor payment records should include payment method, bank account, payee/vendor, payment date, amount, memo, nullable check number, check status, optional check template reference, link to source bill/payment, and audit trail support. Check writing is expected before practical deployment for real bookkeeping use.

Deferred:

- Plaid-style bank feeds;
- automatic statement import;
- external `bank_transaction.created` ingestion events;
- external `bank_statement_line.created` ingestion events;
- automated reconciliation matching engine;
- printable check generation until the reserved check-writing module is implemented.

### 9.11 Reporting

The UI should present PropertyLedger reports first, while also exposing LedgerOS accounting reports.

PropertyLedger reports:

- rent roll;
- tenant ledger;
- delinquency report;
- property income/expense report;
- owner statement;
- security deposit ledger;
- management-fee expense summary;
- maintenance expense summary.

LedgerOS accounting reports:

- trial balance;
- profit and loss;
- balance sheet;
- period summary;
- tax summary, if applicable.

Report rules:

- report definitions must state basis, period, scope, and sign rules;
- report totals must reconcile to underlying posted activity;
- draft/unposted records must be excluded from financial results;
- drill-down should reconcile to report totals where available.

LedgerOS read APIs should be used for accounting-system-of-record reports and statuses, including trial balance, profit and loss, balance sheet, accounting periods, chart of accounts, invoice/bill/payment status, bank balances, reconciliation status, and audit drill-down.

The PropertyLedger app should compute property-management reports that require property, unit, tenant, lease, owner, or maintenance context, including rent roll, tenant ledger, delinquency report, owner statements, property income/expense, security deposit ledger, maintenance expense summary, management-fee expense summary, and unit-level expense reports.

Real estate financial reports must reconcile to LedgerOS-posted resources where applicable. Draft or unsynced items may be shown for operational visibility, but must be clearly labeled and excluded from official financial totals.

### 9.12 Roles and permissions

MVP supports coarse property-management roles:

| Role | MVP permissions |
|---|---|
| Admin | configure system, users, properties, LedgerOS setup, account mappings, all workflows |
| Property manager | manage properties, units, tenants, leases; review charges/payments/reports; initiate operational workflows |
| Bookkeeper | create/post charges and bills; record payments; perform banking/reconciliation workflows; run reports; correct through approved workflows |
| Owner viewer | design role for future owner access; owner login may be deferred |
| Read-only viewer | view records and reports; no create/post/reverse/configure |

Deferred:

- full fine-grained permission matrix;
- approval chains;
- owner portal permissions;
- tenant portal permissions.

### 9.13 API integration surface

The product must expose a documented integration path for sophisticated users and agent-built connectors.

The PropertyLedger app may expose its own API and must integrate to LedgerOS through an adapter.

LedgerOS write events/resources used by the adapter should include:

- invoice created;
- bill created;
- customer/tenant payment received;
- vendor payment sent;
- credit created;
- refund created.

The adapter must support:

- LedgerOS API client configuration;
- HMAC signing;
- idempotency keys;
- duplicate response handling;
- retry logic;
- external ID mapping;
- request/response logging without leaking secrets.

Bank ingestion events are explicitly deferred.

## 10. Data model summary

### 10.1 Real estate app domain objects

- Property
- Unit
- Owner
- Tenant
- Lease
- TenantCharge
- RentGenerationRun
- TenantPaymentRecord
- SecurityDepositRecord
- VendorExpenseContext
- MaintenanceCategory
- DebtServicePayment
- CreditCardAccount
- CreditCardPayment
- OwnerContributionDistribution
- OwnerStatement
- LedgerOSSyncRecord
- CheckPaymentFields or future CheckWritingModule placeholder

### 10.2 Required sync mapping table

The app must store a sync record for every LedgerOS-bound accounting event.

Suggested fields:

```text
local_object_type
local_object_id
ledgeros_resource_type
ledgeros_resource_id
source_event_type
external_id
idempotency_key
request_hash
response_payload
last_synced_at
status
last_error
property_id
unit_id
owner_id
ledgeros_journal_entry_id
```

## 11. Key user workflows

### 11.1 Initial setup workflow

1. Admin connects LedgerOS.
2. Admin validates API credentials.
3. Admin configures chart/account mappings, including optional debt-service and credit-card mappings.
4. Admin creates first property, owner, unit, tenant, and lease.
5. Admin/bookkeeper generates a test rent invoice.
6. App posts/syncs invoice to LedgerOS.
7. App records a test payment.
8. App runs tenant ledger and property income/expense report.

### 11.2 Monthly rent workflow

```text
Monthly rent workflow

Scheduler/User
      |
      | 1. Generate monthly rent
      v
Real Estate App
      |
      | 2. Create tenant charge for lease period
      v
LedgerOS Adapter
      |
      | 3. Prepare invoice request
      | 4. Add HMAC signature and idempotency key
      v
LedgerOS API
      |
      | 5. Create/post AR invoice through LedgerOS services
      v
LedgerOS Accounting Records
      |
      | 6. Return invoice_id and journal_entry_id
      v
LedgerOS Adapter
      |
      | 7. Store sync mapping and response payload
      v
Real Estate App
      |
      | 8. Show charge as posted/synced
      v
Scheduler/User
```

### 11.3 Tenant payment workflow

1. Bookkeeper selects tenant and open charges.
2. Bookkeeper records payment date, amount, method, and reference.
3. App applies payment to open charges.
4. App sends payment event to LedgerOS.
5. LedgerOS records payment/application.
6. App updates tenant ledger and sync status.

### 11.4 Owner statement workflow

1. User selects owner/property and statement period.
2. App collects rent, payments, expenses, manually recorded management-fee expenses, contributions, and distributions.
3. App reconciles accounting-source totals against LedgerOS posted activity where applicable.
4. App generates owner statement preview.
5. User exports or saves statement.

## 12. Platform shape

MVP includes:

- web app for property managers/bookkeepers;
- backend API for the PropertyLedger app;
- documented API integration path;
- LedgerOS adapter;
- Docker-based local development path.

## 13. Success metrics

MVP is successful when:

1. A technically competent user can set up a realistic property-management entity locally.
2. A bookkeeper can create a property, unit, tenant, lease, rent charge, tenant payment, vendor bill, maintenance expense, and owner statement without touching raw LedgerOS internals.
3. A sophisticated user or agent can build an API client using the documented integration contract.
4. Rent charges and payments sync to LedgerOS without duplicate accounting entries under retry.
5. Owner statements and property reports reconcile to posted accounting activity.
6. Closed/locked accounting periods prevent posting.
7. Posted records are not edited destructively.
8. Credit-card vendor payments and debt-service payments can be tracked with property/unit attribution.
9. Vendor payment data has a reserved path for post-MVP check writing.

## 14. Resolved discussion decisions and remaining open questions

Resolved during review:

1. MVP does not support multiple owners per property or ownership percentages. Use one primary owner per property.
2. Property/unit/lease/owner dimensions live in the PropertyLedger app. LedgerOS-native dimensions are deferred.
3. Owner contributions and distributions use simple equity-style treatment in MVP, with owner/property attribution stored in the PropertyLedger app.
4. LedgerOS read APIs provide accounting-source reports and statuses; the PropertyLedger app computes property-context reports and reconciles to LedgerOS-posted resources.
5. Automated management-fee calculation is deferred. Manual management-fee expenses are allowed.
6. Banking/reconciliation workflows exposed in the real estate UI require controlled LedgerOS APIs; full reconciliation execution may phase in after MVP.
7. Debt servicing and credit-card accounts are included in MVP setup/onboarding.
8. Vendor payments by credit card are supported through credit-card liability accounting.
9. Check writing is deferred from MVP but must have a reserved drop-in path and is expected before practical deployment.

Remaining open questions for implementation planning:

1. Which exact LedgerOS banking APIs already exist versus need to be added for the PropertyLedger app?
2. What check template format should be used for the post-MVP check-writing module?
3. Should unit-level reporting be generated entirely from the PropertyLedger app database or cached in a reporting table?
