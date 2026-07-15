# Implementation Epics — PropertyLedger

## Draft status

This document translates the PropertyLedger PRD into buildable implementation epics for AI agents.

It is intended to prevent the recurring failure mode where an epic is directionally correct but under-specified. Each epic must be implementation-ready before coding begins. If an epic leaves material ambiguity around data fields, statuses, LedgerOS sync, account mappings, attribution, or acceptance checks, the agent must stop and ask for clarification before implementing.

PropertyLedger is a separate real estate accounting application that uses LedgerOS as the accounting backend/system of record.

## Current implementation state

Epic 1 and Epic 2 may already be partially or fully implemented in the repository. This document should not be used to silently rewrite completed work unless a change is explicitly requested.

Use this document as:

1. the forward plan for Epic 3 and later;
2. the standard for judging whether a future epic is ready to implement;
3. the reference for future cleanup or hardening of earlier epics if requested.

If the current code differs from this document, do not assume either is correct. Identify the discrepancy and ask whether to align the code, align the docs, or preserve the existing behavior.

## Implementation principles

1. Build PropertyLedger as a separate application with its own domain database.
2. Treat LedgerOS as the required MVP accounting backend.
3. Keep LedgerOS-specific behavior behind a `ledgeros_adapter` or equivalent accounting adapter boundary.
4. Never directly mutate LedgerOS accounting tables from PropertyLedger.
5. Use LedgerOS APIs/services for accounting mutations.
6. Store a sync mapping for every LedgerOS-bound accounting event.
7. Keep property/unit/owner/tenant/lease attribution in PropertyLedger.
8. Make every epic traceable to PRD requirements.
9. Make deferred scope explicit.
10. Run all development, test, and smoke-check workflows through Docker or Docker Compose.

## Sync meaning

When an epic says PropertyLedger should "sync" an accounting event to LedgerOS, the default expectation is that the sync produces the appropriate posted accounting change in LedgerOS, not merely an audit record.

Only explicitly named audit-only endpoints or flows may persist an event without affecting balances.

## Containerization requirement

PropertyLedger must run containerized from the start.

All epics must preserve the Docker workflow. Do not add setup instructions that require installing Python, Node, Postgres, Redis, or other runtime dependencies directly on the host unless explicitly requested.

Required baseline files:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `.env.example`
- `Makefile` or equivalent scripts
- `scripts/check.sh`, if used by the repo
- `scripts/test.sh`, if used by the repo

The default local workflow should support:

```bash
docker compose build
docker compose up -d
docker compose run --rm propertyledger-web python manage.py check
docker compose run --rm propertyledger-web python manage.py test
```

All automated verification is expected to run in Docker. Do not depend on host Python, host Django packages, or host database services for test execution.

When a real LedgerOS instance is needed, point PropertyLedger at the running LedgerOS endpoint configured in the README. The mock LedgerOS flow, if present, is secondary and does not satisfy the real LedgerOS acceptance checks.

## LedgerOS boundary discipline

PropertyLedger owns:

- properties;
- units;
- owners;
- tenants;
- leases;
- rent roll;
- property/unit attribution;
- owner statement context;
- maintenance expense context;
- local workflow status;
- local UI state;
- LedgerOS sync mappings.

LedgerOS owns:

- chart of accounts;
- accounting periods;
- invoices;
- bills;
- payments;
- journal entries;
- banking/reconciliation records;
- accounting reports;
- audit trail;
- accounting invariants.

PropertyLedger must interact with LedgerOS through controlled APIs or adapter methods. Do not import LedgerOS Django models into PropertyLedger domain code, write directly to the LedgerOS database, or treat PropertyLedger local records as posted accounting facts until LedgerOS sync succeeds.

## Future Epic Definition Rules

Before implementing any epic after Epic 2, review the epic against this section. An epic is not implementation-ready unless it defines the following items.

### 1. Scope boundary

Each epic must clearly state what is included and excluded.

The epic must distinguish:

- setup/configuration work;
- local PropertyLedger domain records;
- LedgerOS-bound accounting events;
- reports/read models;
- UI-only workflow support;
- deferred future features.

Do not infer scope from the PRD if the epic text is narrower. If the PRD and epic conflict, stop and ask.

### 2. Required data model fields

For each new model, the epic must define required fields, nullable fields, defaults, uniqueness constraints, and archive/delete behavior.

Money fields must specify:

- decimal amount field;
- whether negative amounts are allowed;
- rounding behavior;
- whether the value is user-entered, generated, imported, or calculated.

Date fields must specify:

- required or optional;
- default behavior;
- whether the date controls accounting period selection;
- timezone expectations if datetime is used.

### 3. Status/state lifecycle

Any object with a status must define:

- allowed statuses;
- initial status;
- valid transitions;
- invalid transitions;
- which service/action owns each transition;
- whether status can be changed manually;
- how archived records behave.

Setup status, local workflow status, and LedgerOS sync status must remain separate.

### 4. LedgerOS interaction contract

Each LedgerOS-bound workflow must define:

- which PropertyLedger action triggers LedgerOS sync;
- which LedgerOS endpoint/resource is used;
- required request payload fields;
- expected response fields;
- idempotency key format;
- retry behavior;
- failure behavior;
- whether the local record can be edited after successful sync.

If LedgerOS does not expose the needed API, the epic must say whether to add a LedgerOS API, defer the workflow, or keep the workflow local-only. Do not bypass LedgerOS services.

### 5. Account mappings

Any workflow that creates accounting impact must name the required account mappings.

The epic must specify:

- required mappings;
- optional mappings;
- expected LedgerOS account type for each mapping;
- failure behavior if a mapping is missing or invalid.

### 6. Property/unit/owner attribution

Any income, expense, charge, payment, deposit, bill, adjustment, or reportable event must define whether it requires:

- property;
- unit;
- owner;
- tenant;
- lease;
- vendor;
- maintenance category.

If attribution is optional, the epic must explain when it may be blank and how reports handle blank attribution.

### 7. Idempotency and sync behavior

Every LedgerOS-bound event must create or update a `LedgerOSSyncRecord`.

The epic must define:

- local object type;
- source event type;
- external ID format;
- idempotency key format;
- expected sync status transitions;
- duplicate handling;
- whether retry is automatic, manual, or both.

### 8. Acceptance criteria

Acceptance criteria must be executable and specific.

Each epic must include:

- automated test expectations;
- Docker Compose commands to run;
- manual smoke/acceptance checks;
- expected UI behavior, if UI is included;
- expected LedgerOS sync records, if accounting sync is included;
- expected report totals, if reporting is included.

### 9. Explicit out-of-scope list

Each epic must include an out-of-scope section. If a feature is mentioned in the PRD but not implemented in the epic, it must be explicitly deferred.

### 10. Blocking open questions

Open questions must be classified as:

- blocks implementation;
- does not block implementation;
- deferred product decision.

Agents must not begin implementation if any blocking question remains unresolved.

## Global domain decisions

These decisions apply to all epics unless a later approved decision changes them.

### Product scope

PropertyLedger is accounting-first with optional property-management extensions. It is not a full property-management platform in the MVP.

### Primary customer

The first target customer is a property manager managing units on behalf of owners.

### Portfolio model

MVP uses one LedgerOS accounting entity for the property-management business. Properties, units, owners, tenants, leases, and real estate reporting dimensions live in PropertyLedger.

### Ownership model

MVP enforces one primary owner per property. Fractional ownership, multiple owners per property, ownership percentages, ownership effective dates, and owner groups are deferred.

### Accounting basis

MVP uses accrual-style operational workflows. Rent charges create receivables; vendor bills create payables; tenant and vendor payments apply against open items. Refined cash-basis reporting is deferred.

### Rent model

MVP supports lease-based recurring base monthly rent and manual one-off tenant charges. A full recurring-charge engine, automatic late fees, rent escalations, and non-monthly cadence are deferred.

### Security deposits

Security deposits are tracked as liabilities with manual deduction/refund workflows. Jurisdiction-specific compliance, interest calculation, statutory notices, and legal deposit letters are deferred.

### Management fees

Automated management-fee calculation is deferred. A management fee may be manually recorded as a property-level expense through the normal expense/bill/journal workflow.

### Payments

Tenant payments are manual in MVP. Online rent collection, ACH/card processor integration, payment webhooks, failed-payment workflows, processor fee automation, and tenant portal payments are deferred.

### Banking

MVP supports guided banking actions and status visibility through controlled LedgerOS APIs where available. Automated bank-feed ingestion, external bank event ingestion, automatic statement import, and automated matching are deferred.

### Check writing

Printable check generation is deferred from initial MVP but expected before practical deployment for real bookkeeping use. Vendor payment data models must reserve enough structure to add check writing without redesigning payments.

### Reporting split

LedgerOS provides accounting-source-of-truth reports and statuses. PropertyLedger computes property-context reports using local real estate records and sync mappings, and those reports must reconcile to LedgerOS-posted resources where applicable.

## Global data and state standards

### Money fields

Use decimal money amounts, not floats. Do not store currency fields in MVP. Treat all money amounts as project-default currency amounts.

Unless an epic explicitly permits negative amounts, user-entered money fields must be non-negative and direction must be expressed through workflow type, side, or accounting treatment.

### Archive/delete behavior

For business records that may have accounting impact, prefer archive/inactivate over hard delete. Do not delete records that are referenced by synced accounting activity.

### Setup status

Setup status is owned by setup/configuration models such as `PropertyLedgerSetup`.

Allowed setup statuses:

- `not_started`
- `in_progress`
- `blocked`
- `validated`
- `complete`

Setup status answers: "Is PropertyLedger configured well enough to run workflows?"

### LedgerOS sync status

Accounting sync status is owned by `LedgerOSSyncRecord`.

Allowed sync statuses:

- `pending`
- `in_progress`
- `succeeded`
- `failed`
- `duplicate`
- `cancelled`

Sync status answers: "Has this specific local event been submitted to LedgerOS, and what happened?"

Setup status and sync status must not share a field or enum.

### Required setup account mappings

The core setup must validate these mappings before setup can be marked complete:

- `operating_bank_account`
- `undeposited_funds`
- `accounts_receivable`
- `accounts_payable`
- `rental_income`
- `repairs_and_maintenance_expense`
- `tenant_security_deposits_liability`
- `owner_contributions_equity`
- `owner_distributions_equity`

Required if enabled:

- `credit_card_liability`
- `mortgage_or_loan_liability`
- `interest_expense`
- `principal_payment_mapping`

Optional/deferred:

- `late_fee_income`
- `management_fee_expense_category`
- `parking_income`
- `storage_income`
- `utility_reimbursement_income`
- `sales_tax_liability`

Setup cannot be marked complete if a required mapping is missing, inactive, or mapped to an invalid LedgerOS account type.

Example required mapping:

| Mapping key | LedgerOS account id | LedgerOS account name | LedgerOS account type |
| --- | --- | --- | --- |
| `operating_bank_account` | `1000` | `Operating Bank` | `asset` |

### LedgerOSSyncRecord standard

Every LedgerOS-bound accounting event must create or update a `LedgerOSSyncRecord`.

Required fields:

- `local_object_type`
- `local_object_id`
- `ledgeros_resource_type`
- `ledgeros_resource_id`, nullable until success
- `ledgeros_journal_entry_id`, nullable
- `source_event_type`
- `external_id`
- `idempotency_key`
- `request_hash`
- `response_payload`, JSON, nullable
- `status`
- `last_error`, nullable
- `attempt_count`
- `last_synced_at`, nullable
- `created_at`
- `updated_at`

Required uniqueness constraints:

- unique `local_object_type`, `local_object_id`, `source_event_type`
- unique `idempotency_key`
- unique `external_id`, `source_event_type`

Do not add alternate sync identity rules in a future epic without documenting the reason, migration impact, and tests.

## Suggested repository shape

The current repository may not exactly match this shape. Future changes should preserve the same boundaries even if names differ.

```text
propertyledger/
  propertyledger/              # Django project/config
  ledgeros/                    # LedgerOS adapter/integration app, if current naming remains
  properties/                  # property/unit/owner domain, if split later
  leasing/                     # tenants/leases/rent roll, if split later
  billing/                     # tenant charges/payments, if split later
  payments/                    # tenant payments and security deposits
  vendors/                     # vendor bills/expenses, if split later
  reporting/                   # real estate reports, if split later
  docs/
    propertyledger-prd.md
    propertyledger-implementation-epics.md
    ledgeros-integration-contract.md
```

Do not rename apps solely for aesthetics. Split apps only when it reduces real coupling and the migration/test impact is justified.

---

# Epic 1 — Containerized foundation and LedgerOS adapter

## Current status

Epic 1 may already be implemented. Treat this section as historical scope plus the standard for future hardening, not permission to rewrite completed work without approval.

## Purpose

Create the base PropertyLedger app, containerized runtime, domain boundaries, LedgerOS connection layer, and safe sync infrastructure.

## In scope

- Django/DRF backend skeleton;
- PostgreSQL database;
- Docker Compose local development;
- real LedgerOS endpoint connectivity as the primary setup path;
- mock LedgerOS mode only as a secondary isolated test mode, if present;
- LedgerOS adapter interface;
- LedgerOS HMAC signing helper;
- idempotency helper;
- API client configuration through environment variables;
- deterministic local and LedgerOS health checks;
- `LedgerOSSyncRecord` model with locked schema and uniqueness constraints;
- basic admin/setup surface.

## Out of scope

- rent generation;
- owner statements;
- online payments;
- bank-feed ingestion;
- tenant portal;
- billing, payments, reporting, or reconciliation workflows beyond connectivity and sync infrastructure.

## Decisions

- Backend framework: Django + Django REST Framework.
- Database: PostgreSQL.
- Runtime: Docker Compose.
- Full production frontend: out of scope for Epic 1.
- Secrets: environment variables only for Epic 1; do not store HMAC secrets/API keys in the database.
- LedgerOS health endpoint: use configured `LEDGEROS_HEALTH_PATH`, defaulting to the real LedgerOS health endpoint documented in `.env.example`/README.

## Acceptance criteria

- App boots locally with Docker Compose.
- The default setup path starts PropertyLedger and verifies connectivity to a real LedgerOS instance.
- Local health check reports PropertyLedger app and database status.
- LedgerOS health check reports healthy only for expected successful LedgerOS response.
- App can create and persist a sync record.
- Adapter can sign a sample request.
- Secrets are not logged.
- Tests cover HMAC signing, idempotency-key generation, sync-record uniqueness, and health checks.

## Docker/manual checks

Use the commands documented in the README for the current repo. At minimum, a real LedgerOS acceptance path must verify:

- PropertyLedger container starts;
- PropertyLedger database is reachable;
- LedgerOS database is reachable;
- PropertyLedger can call the configured LedgerOS health endpoint from inside Docker;
- checks/tests run inside containers.

---

# Epic 2 — Setup foundation and core real estate master data

## Current status

Epic 2 may already be implemented. Do not retrofit it solely because this document is stricter unless the user requests that work.

## Purpose

Allow a property manager/admin to configure the minimum viable operating portfolio and required LedgerOS setup before accounting workflows begin.

Epic 2 gets the system ready. Later epics create accounting activity.

## In scope

- setup wizard or setup/admin flow;
- LedgerOS connection validation;
- LedgerOS health/API configuration validation;
- LedgerOS entity selection/confirmation;
- chart of accounts import/confirmation;
- first open accounting period selection;
- required account mapping setup and validation;
- required bank and credit-card account mapping;
- optional debt-service mappings;
- persisted setup status;
- property records;
- unit records;
- owner records;
- tenant records;
- lease records;
- base monthly rent amount;
- required security deposit amount;
- lease status;
- archive behavior for master data.

## Out of scope

- multi-entity owner books;
- tenant portal;
- fractional ownership;
- multiple owners per property;
- document management;
- real rent generation;
- invoices;
- bills;
- payments;
- owner statements;
- check writing.

## Required data definitions

### Lease rent fields

- `base_monthly_rent_amount`: required decimal money amount.
- `rent_billing_cadence`: `monthly` only for MVP.
- `rent_effective_date`: defaults to lease start date.

Deferred: rent escalations, multiple rent periods, non-monthly cadence, automatic proration, full recurring-charge schedules.

### Security deposit fields

- `security_deposit_required_amount`: required decimal money amount, default `0.00`.

`deposit_required` means a required amount, not a boolean and not a workflow status.

### Lease statuses

Allowed statuses:

- `draft`
- `active`
- `ended`
- `cancelled`

A lease cannot be active without property, unit, tenant, start date, and base monthly rent amount.

### Owner model

MVP enforces one primary owner per property. An owner may own many properties. A property may not have multiple active owners in MVP.

## Required setup state

A setup/configuration model such as `PropertyLedgerSetup` must persist:

- LedgerOS base URL or reference;
- selected LedgerOS entity ID/name;
- selected accounting period ID/name/start/end;
- setup status;
- LedgerOS health status;
- account mapping validation status;
- bank/card mapping validation status;
- last validated timestamp;
- completion timestamp.

Allowed setup statuses:

- `not_started`
- `in_progress`
- `blocked`
- `validated`
- `complete`

Setup is complete only when:

- LedgerOS health succeeds;
- LedgerOS entity is selected;
- an open accounting period is selected;
- required mappings are valid;
- required bank/card mappings are valid;
- setup smoke validation passes.

## Acceptance criteria

- User can create a property, unit, owner, tenant, and active lease.
- The model enforces one primary owner per property.
- Lease requires unit, tenant, start date, and base monthly rent amount.
- Security deposit requirement is stored as an amount, not a boolean.
- Setup flow validates the required LedgerOS mappings listed in this document.
- Setup cannot be marked complete if a required mapping is missing or invalid.
- Setup persists setup status separately from accounting sync status.
- Property/unit/tenant/lease records can be archived without deleting accounting history.
- UI clearly distinguishes setup status from accounting sync status.

---

# Epic 3 — Rent generation and tenant charges

## Purpose

Generate monthly base rent from active leases, support manual one-off tenant charges, and sync approved charges to LedgerOS invoices through the adapter.

## Implementation-readiness requirement

Before coding Epic 3, produce a short decision log covering:

- charge model fields;
- charge statuses and transitions;
- rent generation period identity;
- idempotency key format;
- LedgerOS invoice payload;
- account mappings used for each charge type;
- edit rules before and after LedgerOS sync;
- how draft/unsynced charges appear in tenant ledgers.

Do not implement Epic 3 if these items are unresolved.

## In scope

- generate base monthly rent charges from active leases;
- prevent duplicate rent generation for the same lease and billing period;
- manual one-off tenant charges;
- property-level manual charges not attached to a lease;
- tenant charge statuses;
- charge approval/post-to-LedgerOS action;
- LedgerOS invoice sync through adapter;
- charge-level sync status via `LedgerOSSyncRecord`;
- tenant ledger draft/open view.

## Out of scope

- full recurring-charge engine for every fee type;
- automatic late fees;
- online payments;
- tenant portal;
- rent escalations;
- automatic proration;
- non-monthly rent cadence;
- cash-basis reporting.

## Required data definitions

### TenantCharge

Required fields:

- property;
- unit, required for lease-based rent, optional for property-level manual charges;
- tenant, required for lease-based rent, optional for manual charges;
- lease, required for lease-based rent, optional for manual charges;
- charge_type;
- billing_period_start;
- billing_period_end;
- charge_date;
- due_date;
- amount;
- description;
- status;
- created_at;
- updated_at.

Allowed charge types:

- `base_rent`
- `utility_reimbursement`
- `late_fee_manual`
- `other_manual`

Allowed charge statuses:

- `draft`
- `approved`
- `ready_to_sync`
- `posted`
- `voided`

Initial status: `draft`.

Valid transitions:

- `draft` -> `approved`
- `approved` -> `ready_to_sync`
- `ready_to_sync` -> `posted`
- `draft` -> `voided`
- `approved` -> `voided`, only if not posted

Once `posted`, do not edit amount, tenant, lease, period, account mapping, or charge type. Corrections after posting must use credit/adjustment workflows in later epics.

## Rent generation identity

A generated base rent charge is unique by:

- lease;
- charge type `base_rent`;
- billing period start;
- billing period end.

Duplicate generation for the same lease/month must be blocked unless a future approved correction workflow explicitly permits it.

Base rent for a lease that starts or ends mid-month must be prorated for the affected billing period.

## Required account mappings

- `accounts_receivable`
- `rental_income`

Manual charge types may require additional optional mappings only if implemented. If a manual charge type lacks a valid mapping, the charge may be saved as draft but cannot be approved for LedgerOS sync.

Approving a charge immediately starts LedgerOS sync. The local charge status records workflow state, while the related `LedgerOSSyncRecord` records the LedgerOS posting outcome. After posting, only `due_date` and `description` remain editable.

## LedgerOS sync contract

LedgerOS resource: invoice.

Source event type: `tenant_charge.invoice_created`.

External ID format:

```text
tenant-charge:{tenant_charge_id}
```

Idempotency key format:

```text
propertyledger:tenant-charge:{tenant_charge_id}:invoice-created:v1
```

Required response fields from LedgerOS:

- invoice/resource ID;
- journal entry ID, if LedgerOS returns it;
- status or posted indicator.

## Acceptance criteria

- User can generate rent for a selected month from active leases.
- Rent generation is idempotent for lease/month.
- User can create manual one-off charge.
- User can create manual charge not attached to a lease.
- Charge cannot sync without required mappings.
- Posted charge creates a LedgerOS invoice through the adapter.
- Retried sync does not duplicate the LedgerOS invoice.
- Tenant ledger shows draft, approved, ready-to-sync, and posted charges distinctly.
- Posted charges are not destructively editable.
- Tests cover duplicate rent generation, charge status transitions, required mapping validation, idempotency key generation, sync retry behavior, and tenant ledger visibility.

## Docker/manual checks

- Run tests inside Docker.
- Generate rent for a sample active lease.
- Verify one charge appears for the month.
- Re-run generation and verify no duplicate charge.
- Sync the charge and verify a `LedgerOSSyncRecord` is created/updated.

---

# Epic 4 — Tenant payments, credits, and security deposits

## Purpose

Record manual tenant payments, apply them to open tenant charges, and track security deposits as liabilities.

## Implementation-readiness requirement

Before coding Epic 4, produce a short decision log covering:

- payment statuses;
- payment application rules;
- partial payment behavior;
- overpayment/credit behavior;
- security deposit receipt/deduction/refund accounting treatment;
- LedgerOS payment/credit/refund payloads;
- edit rules after sync.

## In scope

- manual tenant payment recording;
- payment application to open tenant charges;
- partial payments;
- overpayment/credit handling where supported by LedgerOS contract;
- payment sync to LedgerOS;
- security deposit required/received/held tracking;
- manual deposit deduction;
- manual deposit refund;
- security deposit ledger.

## Out of scope

- online rent collection;
- ACH/card processor integration;
- failed-payment workflows;
- processor fee automation;
- payment webhooks;
- statutory deposit documents;
- deposit interest calculation;
- jurisdiction-specific security deposit compliance;
- tenant portal.

## Required data definitions

### TenantPayment

Required fields:

- property;
- tenant;
- payment_date;
- amount;
- payment_method;
- reference, optional;
- status;
- unapplied_amount;
- created_at;
- updated_at.

Allowed payment methods:

- `cash`
- `check`
- `ach_manual`
- `card_manual`
- `other`

Allowed payment statuses:

- `draft`
- `allocated`
- `ready_to_sync`
- `posted`
- `voided`

### TenantPaymentApplication

Required fields:

- tenant payment;
- tenant charge;
- amount applied;
- created_at.

Total applications may not exceed payment amount. A charge may be partially paid. A payment may be partially applied if overpayment/credit handling is enabled; otherwise unapplied amounts must block sync.

### SecurityDepositRecord

Required fields:

- property;
- unit;
- tenant;
- lease;
- event_type;
- event_date;
- amount;
- description;
- status;
- sync record reference where applicable.

Allowed statuses:

- `draft`
- `ready_to_sync`
- `posted`
- `voided`

Allowed event types:

- `required`
- `received`
- `deducted`
- `refunded`

## Required account mappings

For rent/customer payments:

- `undeposited_funds` or operating bank/clearing account according to LedgerOS payment contract;
- `accounts_receivable`.

For security deposits:

- `tenant_security_deposits_liability`;
- `undeposited_funds` or operating bank/clearing account according to LedgerOS payment contract.

## LedgerOS sync contract

LedgerOS must expose a generic sync-event endpoint for Epic 4.

Required LedgerOS resource and expected request shape:

- `POST /api/v1/sync-events/`
  - persists one downstream accounting event;
  - request includes `source_system`, `domain_event_type`, `external_id`, `source_object_type`, `source_object_id`, `occurred_at`, and `payload`.

The `payload` body carries the property-specific details for tenant payments, payment allocations, and security deposit events. Keep PropertyLedger business logic local and send only generic sync events to LedgerOS. Do not route Epic 4 payment or deposit sync through a journal fallback in PropertyLedger.

Required source event types:

- `tenant_payment.received`
- `security_deposit.received`
- `security_deposit.deducted`
- `security_deposit.refunded`

Idempotency keys must include local object ID, event type, and version.

## Acceptance criteria

- User can record payment against open tenant charges.
- Partial payments reduce tenant balance correctly.
- Payment applications cannot exceed payment amount or open charge amount.
- Payment sync to LedgerOS is idempotent.
- Security deposit receipt increases tenant deposit balance and syncs liability treatment.
- Deposit deduction/refund updates tenant deposit ledger.
- Synced payments/deposit events are not destructively editable.
- Tests cover partial payments, overpayment handling, deposit ledger balance, sync idempotency, and status transitions.

## Docker/manual checks

- Run tests inside Docker.
- Create charge, record partial payment, verify tenant ledger balance.
- Record security deposit receipt and verify deposit ledger balance.
- Retry sync and verify no duplicate LedgerOS resource.

---

# Epic 5 — Vendor bills, credit cards, debt service, and maintenance expenses

## Current status

Epic 5 is complete. The implemented flow covers vendor records, vendor bills, maintenance categories, vendor payments, credit-card vendor payments, credit-card payoff handling, debt-service payments, and the supporting accounting sync behavior.

## Purpose

Support vendor bills, property/unit expense attribution, credit-card-paid vendor bills, manual debt-service payments, and accounting-relevant maintenance tracking.

## Implementation-readiness requirement

Before coding Epic 5, produce a short decision log covering:

- vendor bill statuses;
- vendor payment statuses;
- credit card account/payment fields;
- AP-clearing treatment for credit-card payments;
- debt-service principal/interest fields;
- required account mappings;
- LedgerOS bill/payment/journal payloads;
- edit rules after sync.

## In scope

- vendor records;
- vendor bills;
- property attribution;
- optional unit attribution;
- maintenance categories;
- repair notes;
- tenant-chargeable flag;
- vendor payment recording;
- vendor payments by credit card through credit-card liability accounting;
- credit-card payoff workflow from bank account;
- manual debt-service payment with principal/interest split;
- LedgerOS bill/payment sync;
- maintenance expense summary.

## Out of scope

- work orders;
- tenant maintenance requests;
- vendor dispatch;
- photo uploads;
- approval workflow;
- automatic credit-card feed ingestion;
- receipt OCR;
- automatic card statement reconciliation;
- amortization schedule generation;
- automatic principal/interest split calculation.

## Required data definitions

### VendorBill

Required fields:

- vendor;
- property;
- unit, optional;
- bill_date;
- due_date, optional;
- amount;
- expense_category;
- maintenance_category, optional;
- repair_notes, optional;
- tenant_chargeable flag;
- status;
- created_at;
- updated_at.

Allowed statuses:

- `draft`
- `ready_to_sync`
- `posted`
- `voided`

Vendor bills do not need a separate approval state in Epic 5. A saved bill should move directly into sync when the required prerequisites are present, and otherwise remain locally saved until those prerequisites are satisfied.

### VendorPayment

Required fields:

- vendor;
- vendor bill;
- payment_date;
- amount;
- payment_method;
- bank_account or credit_card_account, depending on payment method;
- memo, optional;
- check_number, nullable;
- check_status;
- status.

Allowed payment methods:

- `manual_check`
- `ach_manual`
- `credit_card`
- `cash`
- `other`

Allowed check statuses:

- `not_applicable`
- `pending_print`
- `printed`
- `voided`

Check writing itself is deferred, but these fields reserve the drop-in place.

### DebtServicePayment

Required fields:

- property;
- lender/vendor;
- payment_date;
- total_amount;
- principal_amount;
- interest_amount;
- loan liability account mapping;
- interest expense account mapping;
- payment account;
- status.

Principal plus interest must equal total amount unless a later escrow/fee component is explicitly added.

Allowed statuses:

- `draft`
- `ready_to_sync`
- `posted`
- `voided`

## Required account mappings

Vendor bills:

- `accounts_payable`
- relevant expense account, such as `repairs_and_maintenance_expense`

Credit-card vendor payments:

- `accounts_payable`
- `credit_card_liability`

Credit-card payoff:

- `credit_card_liability`
- `operating_bank_account`

Debt service:

- `mortgage_or_loan_liability`
- `interest_expense`
- `operating_bank_account`

## Required accounting treatment

Vendor bill:

```text
Debit  Expense
Credit Accounts Payable
```

Vendor bill paid by credit card:

```text
Debit  Accounts Payable
Credit Credit Card Liability
```

Credit card payoff:

```text
Debit  Credit Card Liability
Credit Operating Bank Account
```

Debt-service payment:

```text
Debit  Mortgage/Loan Liability    principal amount
Debit  Interest Expense           interest amount
Credit Operating Bank Account     total amount
```

## LedgerOS sync contract

LedgerOS resources should match the authoritative LedgerOS contract for the workflow:

- vendor bills use `POST /api/v1/bills/`;
- vendor provisioning uses `POST /api/v1/vendors/`;
- standard vendor bill payments use `POST /api/v1/payments/`;
- workflows without a dedicated LedgerOS endpoint, such as credit-card vendor liability handling or debt service, use a generic sync-event that LedgerOS converts into a posted journal entry.

Required source event types:

- `vendor_bill.created`
- `vendor_payment.sent`
- `vendor_payment.credit_card`
- `credit_card.payoff`
- `debt_service.payment_recorded`

If LedgerOS lacks a required endpoint for a workflow, stop and ask whether to add a LedgerOS API, use an existing approved journal workflow, or defer the workflow.

## Acceptance criteria

- User can create vendor bill assigned to property and optional unit.
- User can tag bill with maintenance category.
- User can mark expense as tenant-chargeable.
- Bill syncs to LedgerOS without duplicate accounting entries under retry.
- Standard vendor payment syncs to LedgerOS.
- Credit-card vendor payment and credit-card payoff post the expected AP, liability, and bank accounting effect through the LedgerOS sync-event journal bridge.
- Debt-service payment records principal and interest split.
- Principal plus interest equals total debt-service payment.
- Maintenance expense report includes categorized expenses.
- Synced bills/payments are not destructively editable.
- Tests cover attribution, credit-card accounting treatment, debt-service split validation, sync idempotency, and maintenance reporting inputs.

## Docker/manual checks

- Run tests inside Docker.
- Create vendor bill for a property/unit.
- Pay bill by credit card and verify local status/sync record.
- Record credit card payoff.
- Record debt-service payment with principal/interest split.

---

# Epic 6 — Banking, reconciliation visibility, and check-writing foundation

## Purpose

Expose guided banking and reconciliation actions without implementing automated bank-feed ingestion, and reserve the check-writing workflow needed before practical deployment.

## Decision log

Epic 6 has been clarified and partially implemented against the sibling LedgerOS v2 API surface.

Confirmed decisions:

- Epic 6 scope for this pass: MVP banking and reconciliation visibility only
- Missing LedgerOS banking API handling: add the narrow LedgerOS API only if a required read/write surface is absent
- Reconciliation scope for this pass: visibility only
- Deposit and withdrawal payloads: use whatever LedgerOS already exposes
- No LedgerOS code change was required for the current MVP visibility pass

Current implementation status:

- PropertyLedger now consumes the existing LedgerOS banking endpoints for visibility
- The banking UI is read-only for Epic 6 MVP
- Check writing remains deferred unless explicitly expanded later

See also:

- [`docs/epic-6.md`](epic-6.md)

## Implementation-readiness requirement

Before coding Epic 6, produce a short decision log covering:

- which LedgerOS banking APIs exist;
- which new LedgerOS APIs, if any, are required;
- deposit and withdrawal payloads;
- reconciliation status read model;
- check-writing placeholder fields already available from Epic 5;
- what is MVP versus post-MVP required deployment feature.

## In scope

- view LedgerOS bank accounts;
- view bank account balances/statuses;
- record deposits through controlled workflow where LedgerOS API exists;
- record withdrawals through controlled workflow where LedgerOS API exists;
- show reconciliation status;
- show unmatched/unreconciled activity where LedgerOS API exists;
- ensure vendor-payment records have fields needed for later check writing;
- document check-writing drop-in design.

## Out of scope

- Plaid or other bank feeds;
- automatic statement import;
- external bank event ingestion;
- fully automated matching engine;
- printable check generation unless explicitly pulled into this epic;
- positive pay/export unless explicitly pulled into check-writing work.

## Required LedgerOS APIs/read contracts

MVP banking UI requires controlled LedgerOS APIs for:

- bank-account list;
- bank-account balance/status;
- manually recording deposit;
- manually recording withdrawal;
- unreconciled activity read, if displayed;
- reconciliation status read.

If any are missing, the epic must explicitly choose one:

1. add the narrow LedgerOS API;
2. defer that UI action;
3. keep it read-only.

Do not call LedgerOS internals or rely on Django Admin workflows from PropertyLedger.

## Acceptance criteria

- Bookkeeper can view bank account status.
- Bookkeeper can record deposit/withdrawal only through controlled actions.
- Reconciliation status is visible by account/period where LedgerOS supports it.
- No external bank ingestion event is accepted in MVP.
- Missing LedgerOS banking API results in clear disabled/deferred UI behavior, not direct DB access.
- Vendor payment records include payment method, bank account, memo, nullable check number, check status, and enough structure for a post-MVP check-writing module.
- Tests cover API availability handling, deposit/withdrawal service calls, and disabled behavior where API support is missing.

## Post-MVP required deployment feature: check writing

Check writing may be implemented as part of Epic 6 if explicitly requested; otherwise it remains the named post-MVP required deployment feature below.

The design must preserve:

- configurable check templates;
- printable check output;
- check alignment settings;
- check number sequencing;
- void check workflow;
- reprint controls;
- audit trail for printed/reprinted/voided checks;
- link from check payment to vendor bill/payment record.

---

# Epic 7 — Owner statements and manual owner activity

## Purpose

Produce owner statements and support manual owner contributions, owner distributions, and manually recorded management-fee expenses.

## Implementation-readiness requirement

Before coding Epic 7, produce a short decision log covering:

- owner statement period rules;
- which records appear on owner statements;
- property attribution requirements;
- owner contribution/distribution accounting treatment;
- reconciliation to LedgerOS-posted activity;
- export/save behavior.

## In scope

- owner statement generation;
- owner statement preview;
- owner statement saved record or export, if selected by implementation;
- manual management-fee expense display where recorded;
- owner contributions/distributions as manual records;
- owner/property attribution for all statement lines;
- reconciliation of statement totals to posted/synced activity.

## Out of scope

- automated owner payable;
- owner ACH payout;
- owner portal;
- automated management-fee calculation;
- complex fee schedules;
- leasing commissions;
- vacancy fees;
- automated owner payable/distribution subsystem;
- multi-entity owner books;
- fractional ownership.

## Required data definitions

### OwnerContributionDistribution

Required fields:

- owner;
- property;
- event_type;
- event_date;
- amount;
- payment_account or bank account reference;
- description;
- status;
- sync record, if LedgerOS-bound.

Allowed event types:

- `contribution`
- `distribution`

MVP accounting treatment is equity-style:

Owner contribution:

```text
Debit  Cash
Credit Owner Contributions / Equity
```

Owner distribution:

```text
Debit  Owner Distributions / Retained Earnings
Credit Cash
```

PropertyLedger stores owner/property attribution. MVP does not implement true separate owner equity ledgers.

## Owner statement contents

An owner statement must show:

- owner;
- property;
- statement period;
- rent charged;
- rent collected;
- property expenses;
- maintenance expenses;
- manually recorded management-fee expenses;
- owner contributions;
- owner distributions;
- security deposit activity if relevant to the owner view;
- net summary.

Draft/unsynced records may be shown for operational visibility only if clearly labeled. Official totals must reconcile to posted/synced activity.

## Acceptance criteria

- User can manually record owner contributions and owner distributions with property attribution.
- User can manually record management-fee expenses through normal expense/bill/journal workflow.
- Owner statement shows rent collected, expenses, manually recorded management-fee expenses, contributions/distributions, and net summary.
- Statement totals reconcile to underlying posted/synced activity.
- Statement clearly excludes or labels draft/unsynced items.
- Tests cover statement period filtering, attribution, contribution/distribution treatment, and reconciliation to synced records.

## Docker/manual checks

- Run tests inside Docker.
- Create owner/property activity across a statement period.
- Generate owner statement and compare totals to source records.

---

# Epic 8 — Reports and dashboards

## Purpose

Expose PropertyLedger reports first while preserving access to LedgerOS accounting reports.

## Implementation-readiness requirement

Before coding Epic 8, produce a report definition table. Each report must define:

- purpose;
- source records;
- period/date basis;
- scope filters;
- whether it includes draft/unsynced items;
- how totals reconcile to LedgerOS;
- drill-down behavior.

## In scope

- rent roll;
- tenant ledger;
- delinquency report;
- property income/expense;
- owner statement view/report link;
- security deposit ledger;
- management-fee expense summary;
- maintenance expense summary;
- links to LedgerOS trial balance, P&L, balance sheet, period summary, and tax summary where available.

## Out of scope

- arbitrary report builder;
- SQL report builder;
- cash-basis owner statements;
- advanced tax reporting;
- custom dashboard designer.

## Reporting split

LedgerOS read APIs should be used for accounting-system-of-record reports and statuses, including:

- trial balance;
- profit and loss;
- balance sheet;
- accounting periods;
- chart of accounts;
- invoice/bill/payment status;
- bank balances;
- reconciliation status;
- audit drill-down.

PropertyLedger computes property-management reports that require property, unit, tenant, lease, owner, or maintenance context, including:

- rent roll;
- tenant ledger;
- delinquency report;
- owner statements;
- property income/expense;
- security deposit ledger;
- maintenance expense summary;
- management-fee expense summary;
- unit-level expense reports.

Real estate financial reports must reconcile to LedgerOS-posted resources where applicable. Draft or unsynced items may be shown for operational visibility, but must be clearly labeled and excluded from official financial totals.

## Acceptance criteria

- PropertyLedger reports are accessible from primary navigation.
- Each report defines period and scope.
- Reports exclude draft/unposted accounting activity where official financial totals are shown.
- Drill-down links show source records where practical.
- Property income/expense and owner statement totals reconcile to posted/synced accounting activity.
- LedgerOS accounting-source reports and statuses are read from LedgerOS APIs where available.
- Property/unit/tenant/owner-context reports are computed in PropertyLedger and reconciled to LedgerOS-posted resources.
- Tests cover report filters, period handling, draft exclusion, and reconciliation logic.

## Docker/manual checks

- Run tests inside Docker.
- Generate each MVP report with seeded/sample data.
- Verify at least one report reconciles to LedgerOS-posted source records.

---

# Epic 9 — Roles, permissions, audit, and production readiness

## Purpose

Add MVP role model, audit visibility, and production-readiness basics.

## Implementation-readiness requirement

Before coding Epic 9, produce a coarse permission matrix. It must define what each role can view, create, update, approve/sync, reverse/void, configure, and export.

## In scope

- Admin role;
- Property manager role;
- Bookkeeper role;
- Owner viewer role in model/design, even if login is deferred;
- Read-only viewer role;
- coarse permissions;
- audit/activity log view;
- import/export basics;
- deployment checklist;
- environment variable documentation;
- production secret handling guidance.

## Out of scope

- fine-grained permission matrix;
- approval chains;
- owner portal;
- tenant portal;
- enterprise SSO;
- billing/subscription management.

## Required roles

### Admin

Can configure system, users, properties, LedgerOS setup, account mappings, and all workflows.

### Property manager

Can manage properties, units, tenants, and leases; review charges/payments/reports; initiate operational workflows as allowed.

### Bookkeeper

Can create/post/sync charges and bills, record payments, perform banking/reconciliation workflows, run reports, and correct through approved workflows. Cannot change system-level mappings unless explicitly granted.

### Owner viewer

Role exists in model/design for future owner access. Owner login/portal may remain deferred.

### Read-only viewer

Can view records and reports. Cannot create, post, sync, reverse, configure, or export sensitive data unless explicitly granted.

## Acceptance criteria

- Users can be assigned roles.
- Role permissions are enforced on major workflows.
- Read-only users cannot mutate data.
- Bookkeepers cannot modify system-level mappings unless allowed.
- Audit/activity log shows major successful events.
- Deployment checklist documents environment variables, secrets, LedgerOS connection requirements, Docker commands, and production caveats.
- Tests cover representative allow/deny cases for each role.

## Docker/manual checks

- Run tests inside Docker.
- Create users for each role.
- Verify allowed and denied workflows manually or through tests.

---

# Epic 10 — API documentation and agent-built connector support

## Purpose

Make the system usable by sophisticated users and AI agents building connectors.

## Implementation-readiness requirement

Before coding Epic 10, define which API surface is actually public for PropertyLedger. Do not document internal endpoints as stable public API unless they are intended for external clients.

## In scope

- external API documentation for PropertyLedger app;
- LedgerOS adapter documentation;
- example client prompts;
- example payloads;
- sync error handling guide;
- test sandbox instructions;
- OpenAPI schema if practical;
- API versioning guidance.

## Out of scope

- QuickBooks/Xero connectors;
- payment processor connectors;
- bank-feed connectors;
- tenant portal API;
- owner portal API.

## Required documentation topics

- authentication model;
- idempotency behavior;
- external ID rules;
- retry behavior;
- duplicate handling;
- request/response logging and secret redaction;
- local object IDs versus LedgerOS resource IDs;
- sandbox/LedgerOS startup path;
- examples for tenant charge, tenant payment, vendor bill, and manually recorded management-fee expense.

## Acceptance criteria

- A technical user can build a client using docs alone.
- Example payloads exist for tenant charge, payment, vendor bill, and manual management-fee expense.
- Docs explain idempotency, duplicate handling, retries, and external IDs.
- Agent guidance states not to bypass accounting adapter boundaries.
- OpenAPI schema exists or the doc explains why it is deferred.

## Docker/manual checks

- Run tests inside Docker.
- Validate example payloads against serializers/schemas where practical.
- Confirm docs match actual endpoints.

---

# Post-MVP Required Deployment Feature — Check writing

## Purpose

Add printable check generation to the existing vendor payment workflow without redesigning vendor payments.

This feature is deferred from the first MVP build but expected before practical deployment for real bookkeeping use.

## Depends on

- vendor bills;
- vendor payments;
- bank account setup;
- payment method/status fields;
- check number and check status placeholders;
- audit/activity logging.

## In scope

- configurable check templates;
- printable check output;
- check alignment settings;
- check number sequencing;
- void check workflow;
- reprint controls;
- audit trail for printed, reprinted, and voided checks;
- link from check payment to vendor bill/payment record;
- optional positive-pay/export support if needed.

## Out of scope

- bank-feed ingestion;
- external payment processor integration;
- approval chains unless added separately.

## Required state model

Check-capable vendor payments must distinguish:

- not applicable;
- pending print;
- printed;
- voided.

Voiding a check must use an explicit accounting-safe workflow and must not destructively edit posted accounting facts.

## Acceptance criteria

- Bookkeeper can print a check for an eligible vendor payment.
- Check number is unique per bank account sequence.
- Printed, reprinted, and voided checks are auditable.
- Voiding a check uses an explicit accounting-safe workflow.
- Reprinting is controlled and auditable.

---

# Cross-epic requirement traceability template

Each epic handoff must include:

| Requirement | PRD section | Status | Code location | Test/manual check |
|---|---|---|---|---|
| Example | 9.4 Rent and tenant charges | Implemented/Deferred | path/to/file | test name/check |

## Cross-epic handoff template

Before claiming an epic is complete, an agent must provide:

1. requirements implemented;
2. requirements deferred;
3. blocking questions resolved;
4. files changed;
5. migrations created, if any;
6. automated tests added/updated;
7. Docker/manual checks run;
8. known limitations;
9. screenshots or API examples if UI/API changed;
10. confirmation that LedgerOS accounting invariants were not bypassed.

## Global deferred roadmap

- tenant portal;
- online rent collection;
- payment processor integration;
- automated bank feeds;
- full maintenance work orders;
- owner portal;
- owner payable/distribution subsystem;
- automated management-fee calculation;
- multi-entity owner books;
- fractional ownership;
- jurisdiction-specific deposit compliance;
- tax automation;
- QuickBooks/Xero connectors;
- check writing until the required post-MVP deployment feature is implemented.
