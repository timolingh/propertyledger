# PropertyLedger

**PropertyLedger** is a real estate accounting client for LedgerOS.

It is intended to be built as a separate application from LedgerOS. PropertyLedger owns property-management context such as properties, units, tenants, leases, owners, rent roll, maintenance categories, and owner statements. LedgerOS remains the accounting system of record for invoices, bills, payments, journals, banking, reconciliation, reports, and audit history.

## Current package status

This repository now includes the Epic 1 Django foundation for PropertyLedger:

- Django + Django REST Framework backend;
- PostgreSQL-backed Docker Compose local stack;
- LedgerOS adapter boundary;
- deterministic local and LedgerOS health checks;
- locked `LedgerOSSyncRecord` schema and uniqueness constraints;
- admin/setup screen for LedgerOS connection settings.

## Included docs

- `docs/propertyledger-prd.md` — product requirements document.
- `docs/propertyledger-implementation-epics.md` — buildable implementation epics for AI agents.
- `docs/ledgeros-integration-contract.md` — local Epic 1 LedgerOS integration contract.
- `CLAUDE.md` — guidance for AI agents working on the PropertyLedger repo.

## Core architecture decision

PropertyLedger should be a separate repo from LedgerOS and interact with LedgerOS through a clean adapter/API boundary.

```text
PropertyLedger domain
  -> Accounting adapter interface
  -> LedgerOS adapter implementation
  -> LedgerOS HTTP API/services
```

PropertyLedger must not import LedgerOS models, call LedgerOS Python services directly, or write to the LedgerOS database.

## MVP product direction

PropertyLedger is accounting-first. It targets property managers managing units on behalf of owners.

MVP includes:

- properties, units, tenants, leases, owners;
- recurring base rent generation plus manual tenant charges;
- tenant payments and tenant ledger visibility;
- vendor bills and maintenance expense tracking;
- debt-service and credit-card account support;
- owner statements;
- guided banking workflows through controlled LedgerOS APIs;
- property-management reports that reconcile to LedgerOS posted records;
- documented API/adapter path for sophisticated users and agent-built connectors.

Deferred or post-MVP:

- tenant portal;
- online rent collection;
- automated bank-feed ingestion;
- full maintenance work orders;
- owner portal;
- automated management-fee calculation;
- multi-entity owner books;
- QuickBooks/Xero connectors;
- check writing implementation, although the data model must reserve a drop-in path for it.

## Next recommended step

Start with Epic 1 runtime setup:

1. Copy `.env.example` to `.env` and adjust local values.
2. Run `docker compose up --build`.
3. Open the setup screen at `http://localhost:8000/`.

Before coding, an AI agent should read:

1. `CLAUDE.md`
2. `docs/propertyledger-prd.md`
3. `docs/propertyledger-implementation-epics.md`
4. The LedgerOS docs that define API authentication, idempotency, accounting invariants, reporting invariants, and epic implementation discipline.
