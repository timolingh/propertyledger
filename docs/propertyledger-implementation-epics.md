# Implementation Epics — PropertyLedger

## Draft status

This is a review draft. It translates the PRD into buildable implementation epics for AI agents. Each epic must follow LedgerOS implementation discipline: trace requirements, state assumptions, avoid silent scope expansion, preserve accounting invariants, and provide automated and manual checks.

## Implementation principles

1. Build the PropertyLedger app as a separate application with its own domain database.
2. Treat LedgerOS as the required MVP accounting backend.
3. Keep LedgerOS-specific logic inside a `ledgeros_adapter` or equivalent integration boundary.
4. Never directly mutate LedgerOS accounting tables from the PropertyLedger app.
5. Use LedgerOS APIs/services for accounting mutations.
6. Store sync mappings for every outbound accounting event.
7. Make every epic traceable to PRD requirements.
8. Make deferred scope explicit.

## Suggested repository shape

```text
propertyledger/
  frontend/
    app/
    components/
    screens/
  backend/
    property_domain/
    leasing/
    billing/
    payments/
    maintenance/
    owner_statements/
    reporting/
    accounting_adapter/
      interface.py
      ledgeros_adapter.py
      signing.py
      idempotency.py
    users_permissions/
    tests/
  docs/
    product-prd.md
    implementation-epics.md
    agent-guidance.md
```

## Epic 1 Decision Log

The following decisions remove ambiguity for the containerized project foundation.

### Framework

PropertyLedger uses Django and Django REST Framework for the backend, PostgreSQL for persistence, and Docker Compose for local development/runtime. A production frontend is out of scope for Epic 1.

### LedgerOS credential storage

LedgerOS secrets are configured through environment variables in Epic 1. HMAC secrets, API keys, and other integration secrets must not be stored in the database.

Required environment variables:

- `LEDGEROS_BASE_URL`
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY`, optional
- `LEDGEROS_HEALTH_PATH`, default `/health/`
- `LEDGEROS_TIMEOUT_SECONDS`, default `5`

### Health checks

PropertyLedger must expose a local health check and a LedgerOS connectivity check.

Local health check confirms the PropertyLedger app and database are reachable.

LedgerOS health check calls the configured LedgerOS health endpoint and reports healthy only when LedgerOS returns HTTP 200 within the configured timeout.

Missing configuration, timeout, connection error, authentication failure, non-2xx response, malformed response, or unexpected payload must be reported as unhealthy.

### LedgerOSSyncRecord

Epic 1 must create the `LedgerOSSyncRecord` model.

Required fields:

- `local_object_type`
- `local_object_id`
- `ledgeros_resource_type`
- `ledgeros_resource_id`, nullable
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

Allowed statuses:

- `pending`
- `in_progress`
- `succeeded`
- `failed`
- `duplicate`
- `cancelled`

Required uniqueness constraints:

- unique `local_object_type`, `local_object_id`, `source_event_type`
- unique `idempotency_key`
- unique `external_id`, `source_event_type`

The schema is locked for Epic 1. Do not add new mutable accounting-state fields, alternate identity fields, or status values unless a later epic explicitly requires a migration and corresponding tests.

### LedgerOS contract

Epic 1 must include `docs/ledgeros-integration-contract.md`. This local contract defines the minimum LedgerOS assumptions needed by PropertyLedger until the LedgerOS repo exposes an authoritative versioned API contract.

## Epic 1 — Application foundation and LedgerOS adapter

### Purpose

Create the base app, domain boundaries, LedgerOS connection layer, and safe sync infrastructure.

### In scope

- PropertyLedger app backend skeleton;
- web app skeleton;
- domain database setup;
- LedgerOS adapter interface;
- LedgerOS HMAC signing helper;
- idempotency helper;
- API client configuration;
- deterministic local and LedgerOS health checks;
- `LedgerOSSyncRecord` model with locked schema and uniqueness constraints;
- basic admin/setup screen;
- Docker Compose local development.

### Out of scope

- rent generation;
- owner statements;
- online payments;
- bank-feed ingestion;
- tenant portal;
- billing, payments, reporting, or reconciliation workflows beyond connectivity and sync infrastructure.

### Acceptance criteria

- App boots locally with Docker Compose.
- Admin can enter LedgerOS URL/client ID/secret references via environment-backed configuration.
- Local health check is deterministic and reports the PropertyLedger app and database status.
- LedgerOS health check is deterministic and reports healthy only for an expected successful LedgerOS health response.
- App can create and persist a sync record.
- Adapter can sign a sample request.
- Secrets are not logged.
- Tests cover HMAC signing, idempotency-key generation, sync-record uniqueness, and both health checks.

### Manual checks

```bash
# Start local app stack with Docker Compose
# Run backend checks/tests
# Validate local health check
# Validate LedgerOS connection using configured local LedgerOS instance
```


## Epic 2 — Setup wizard, properties, units, owners, tenants, and leases

### Purpose

Allow a property manager/admin to configure the minimum viable operating portfolio.

### In scope

- setup wizard;
- property records;
- unit records;
- owner records;
- tenant records;
- lease records;
- base monthly rent;
- deposit required;
- lease status;
- account mapping setup;
- first accounting period and LedgerOS setup validation;
- optional debt-service account mappings;
- optional credit-card liability account mappings.

### Out of scope

- multi-entity owner books;
- tenant portal;
- fractional ownership;
- document management.

### Acceptance criteria

- User can create a property, unit, owner, tenant, and active lease.
- Lease requires unit, tenant, start date, and base rent.
- Setup wizard validates required LedgerOS account mappings.
- Property/unit/tenant/lease records can be archived without deleting accounting history.
- UI clearly distinguishes setup status from accounting sync status.

## Epic 3 — Rent generation and tenant charges

### Purpose

Generate monthly base rent from leases and support manual one-off tenant charges.

### In scope

- generate base monthly rent charges;
- prevent duplicate rent generation for the same lease/month;
- manual tenant charges;
- tenant charge statuses;
- LedgerOS invoice sync through adapter;
- charge-level sync status;
- tenant ledger draft view.

### Out of scope

- full recurring-charge engine for every fee type;
- automatic late fees;
- online payments;
- tenant portal.

### Acceptance criteria

- User can generate rent for a selected month.
- Rent generation is idempotent for lease/month.
- User can create manual one-off charge.
- Synced charge creates LedgerOS invoice.
- Retried sync does not duplicate LedgerOS invoice.
- Tenant ledger shows open charges and sync status.

### LedgerOS integration

Use LedgerOS invoice ingestion endpoint through the adapter. Include external IDs based on local charge IDs and billing periods.

## Epic 4 — Tenant payments, credits, and security deposits

### Purpose

Record manual tenant payments, apply them to charges, and track security deposits as liabilities.

### In scope

- manual tenant payment recording;
- partial payment application;
- tenant overpayment/credit handling where supported;
- payment sync to LedgerOS;
- deposit required/received/held tracking;
- manual deposit deduction;
- manual deposit refund;
- security deposit ledger.

### Out of scope

- online rent collection;
- ACH/card processor integration;
- failed-payment workflows;
- statutory deposit documents;
- interest calculation.

### Acceptance criteria

- User can record payment against open tenant charges.
- Partial payments reduce tenant balance correctly.
- Payment sync to LedgerOS is idempotent.
- Security deposit receipt increases tenant deposit balance and syncs accounting treatment.
- Deposit deduction/refund updates tenant deposit ledger.

## Epic 5 — Vendor bills and maintenance expense tracking

### Purpose

Support vendor bills, property/unit expense attribution, and accounting-relevant maintenance tracking.

### In scope

- vendor records;
- vendor bills;
- property and optional unit attribution;
- maintenance categories;
- repair notes;
- tenant-chargeable flag;
- vendor payment recording;
- vendor payments by credit card through credit-card liability accounting;
- credit-card payoff workflow from bank account;
- manual debt-service payment with principal/interest split;
- LedgerOS bill/payment sync;
- maintenance expense summary.

### Out of scope

- work orders;
- tenant maintenance requests;
- vendor dispatch;
- photo uploads;
- approval workflow.

### Acceptance criteria

- User can create vendor bill assigned to property/unit.
- User can tag bill as maintenance category.
- User can mark expense as tenant-chargeable.
- Bill syncs to LedgerOS without duplicate accounting entries under retry.
- Vendor payment syncs to LedgerOS.
- Credit-card vendor payment clears AP and increases credit-card liability rather than reducing bank cash.
- Credit-card payoff reduces credit-card liability and bank cash.
- Debt-service payment records principal and interest split.
- Maintenance expense report includes categorized expenses.

## Epic 6 — Owner statements and manual owner activity

### Purpose

Produce owner statements and support manual owner contributions, owner distributions, and manually recorded management-fee expenses.

### In scope

- owner statement generation;
- manual management-fee expense display where recorded;
- owner contributions/distributions as manual records;
- owner statement export or saved statement record.

### Out of scope

- automated owner payable;
- owner ACH payout;
- owner portal;
- automated management-fee calculation;
- complex fee schedules;
- leasing commissions;
- vacancy fees;
- automated owner payable/distribution subsystem.

### Acceptance criteria

- User can manually record owner contributions and owner distributions with property attribution.
- User can manually record management-fee expenses through normal expense/bill/journal workflow.
- Owner statement shows rent collected, expenses, manually recorded management-fee expenses, contributions/distributions, and net summary.
- Statement totals reconcile to underlying posted/synced activity.

## Epic 7 — Banking and reconciliation UI

### Purpose

Expose guided banking and reconciliation actions without implementing automated bank-feed ingestion.

### In scope

- view LedgerOS bank accounts;
- record deposits through controlled workflow;
- record withdrawals through controlled workflow;
- show reconciliation status;
- show unmatched/unreconciled activity;
- require controlled LedgerOS APIs for bank-account reads, balances, deposits, withdrawals, unreconciled activity, and reconciliation status;
- reserve vendor-payment fields needed for later check writing.

### Out of scope

- Plaid or other bank feeds;
- automatic statement import;
- external bank event ingestion;
- fully automated matching engine;
- printable check generation in MVP.

### Acceptance criteria

- Bookkeeper can view bank account status.
- Bookkeeper can record deposit/withdrawal using controlled action.
- Reconciliation status is visible by account/period.
- No external bank ingestion event is accepted in MVP.
- Vendor payment records include payment method, bank account, memo, nullable check number, check status, and enough structure for a post-MVP check-writing module.

### Implementation note

This epic may require LedgerOS API expansion if current LedgerOS banking workflows are only available through services/admin. Do not bypass LedgerOS services to implement banking actions.

## Epic 8 — Reports and dashboards

### Purpose

Expose PropertyLedger reports first, while preserving access to LedgerOS accounting reports.

### In scope

- rent roll;
- tenant ledger;
- delinquency report;
- property income/expense;
- owner statement view;
- security deposit ledger;
- management-fee expense summary;
- maintenance expense summary;
- links to LedgerOS trial balance, P&L, balance sheet, period summary, tax summary where available.

### Out of scope

- arbitrary report builder;
- SQL report builder;
- cash-basis owner statements;
- advanced tax reporting.

### Acceptance criteria

- PropertyLedger reports are accessible from primary navigation.
- Reports define period and scope.
- Reports exclude draft/unposted accounting activity where financial totals are shown.
- Drill-down links show source records where practical.
- Property income/expense and owner statement totals reconcile to posted/synced accounting activity.
- LedgerOS accounting-source reports and statuses are read from LedgerOS APIs where available.
- Property/unit/tenant/owner-context reports are computed in the PropertyLedger app and reconciled to LedgerOS-posted resources.

## Epic 9 — Roles, permissions, audit, and production readiness

### Purpose

Add MVP role model, audit visibility, and production-readiness basics.

### In scope

- Admin role;
- Property manager role;
- Bookkeeper role;
- Owner viewer role in model/design, even if login is deferred;
- Read-only viewer role;
- coarse permissions;
- audit/activity log view;
- import/export basics;
- deployment checklist.

### Out of scope

- fine-grained permission matrix;
- approval chains;
- owner portal;
- tenant portal;
- enterprise SSO.

### Acceptance criteria

- Users can be assigned roles.
- Role permissions are enforced on major workflows.
- Read-only users cannot mutate data.
- Bookkeepers cannot modify system-level mappings unless allowed.
- Audit/activity log shows major successful events.
- Deployment checklist documents environment variables, secrets, and LedgerOS connection requirements.

## Epic 10 — API documentation and agent-built connector support

### Purpose

Make the system usable by sophisticated users and AI agents building connectors.

### In scope

- external API documentation for PropertyLedger app;
- LedgerOS adapter documentation;
- example client prompts;
- example payloads;
- sync error handling guide;
- test sandbox instructions;
- OpenAPI schema if practical.

### Out of scope

- QuickBooks/Xero connectors;
- payment processor connectors;
- bank-feed connectors.

### Acceptance criteria

- A technical user can build a client using docs alone.
- Example payloads exist for tenant charge, payment, vendor bill, and manual management-fee expense.
- Docs explain idempotency, duplicate handling, retries, and external IDs.
- Agent guidance states not to bypass accounting adapter boundaries.

## Post-MVP Required Deployment Feature — Check writing

### Purpose

Add printable check generation to the existing vendor payment workflow without redesigning vendor payments. This feature is deferred from the first MVP build but expected before practical deployment for real bookkeeping use.

### Depends on

- vendor bills;
- vendor payments;
- bank account setup;
- payment method/status fields;
- check number and check status placeholders;
- audit/activity logging.

### In scope

- configurable check templates;
- printable check output;
- check alignment settings;
- check number sequencing;
- void check workflow;
- reprint controls;
- audit trail for printed, reprinted, and voided checks;
- link from check payment to vendor bill/payment record;
- optional positive-pay/export support if needed.

### Out of scope

- bank-feed ingestion;
- external payment processor integration;
- approval chains unless added separately.

### Acceptance criteria

- Bookkeeper can print a check for an eligible vendor payment.
- Check number is unique per bank account sequence.
- Printed, reprinted, and voided checks are auditable.
- Voiding a check uses an explicit accounting-safe workflow and does not destructively edit posted facts.

## Cross-epic requirement traceability template

Each epic handoff must include:

| Requirement | PRD section | Status | Code location | Test/manual check |
|---|---|---|---|---|
| Example | 9.4 Rent and tenant charges | Implemented/Deferred | path/to/file | test name/check |

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

## Agent handoff checklist

Before claiming an epic is complete, an agent must provide:

1. requirements implemented;
2. requirements deferred;
3. files changed;
4. migrations created, if any;
5. automated tests added/updated;
6. Docker/manual checks run;
7. known limitations;
8. screenshots or API examples if UI/API changed;
9. confirmation that LedgerOS accounting invariants were not bypassed.
