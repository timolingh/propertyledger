# Epic 7 Runbook

## Purpose

This document captures the agreed scope and decision log for Epic 7 in PropertyLedger.

Epic 7 adds:

- owner statement generation;
- owner statement preview;
- owner statement export;
- manual owner contributions and owner distributions;
- manual management-fee expense visibility through existing expense/bill/journal workflows;
- a pending-sync report for owner statement activity that has not yet posted to LedgerOS.

Epic 7 does not include:

- automated owner payable;
- owner ACH payout;
- owner portal;
- dedicated management-fee entry workflow;
- automated management-fee calculation;
- complex fee schedules;
- leasing commissions;
- vacancy fees;
- automated owner payable/distribution subsystem;
- multi-entity owner books;
- fractional ownership.

## Decision Log

The following decisions are now fixed for Epic 7:

1. Statement scope is `owner + property`.
2. Statement periods are preset `month`, `quarter`, and `year`, while still allowing arbitrary date ranges.
3. Manual owner contributions and owner distributions must sync to LedgerOS so property-level records and accounting records stay aligned.
4. There is no dedicated management-fee entry flow in Epic 7; management-fee expenses are shown only when they already exist in the normal expense/bill/journal workflow.
5. Epic 7 supports preview and export only for the statement artifact; there is no separate persisted statement workflow unless later added.
6. Official statement totals include only synced records. A separate report surfaces items that are pending sync.

## In Scope

- owner statement generation;
- owner statement preview;
- owner statement export;
- owner/property attribution for all statement lines;
- owner contributions and owner distributions as manual records that sync to LedgerOS;
- manual management-fee expense display where recorded through existing workflows;
- reconciliation of statement totals to posted/synced activity;
- pending-sync reporting for statement-related activity.

## Out of Scope

- automated owner payable;
- owner ACH payout;
- owner portal;
- dedicated management-fee expense entry workflow;
- automated management-fee calculation;
- complex fee schedules;
- leasing commissions;
- vacancy fees;
- automated owner payable/distribution subsystem;
- multi-entity owner books;
- fractional ownership.

## Required Data Definitions

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

## Owner Statement Contents

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

Draft or unsynced records must not appear in the official statement totals. They may appear only in the pending-sync report.

## Pending-Sync Report

Epic 7 must provide a separate report or view for statement-related items that are pending sync.

That report should surface:

- owner contributions awaiting LedgerOS posting;
- owner distributions awaiting LedgerOS posting;
- any other statement-related record that has not yet reached a synced state;
- enough context to explain why the item is excluded from official statement totals.

## Acceptance Criteria

- User can generate an owner statement for a selected owner and property.
- User can choose a preset month, quarter, or year statement period, or a custom date range.
- User can manually record owner contributions and owner distributions with property attribution.
- Owner contributions and owner distributions sync to LedgerOS and appear in statement totals only after sync succeeds.
- Manual management-fee expenses appear on the statement only when they were entered through existing expense/bill/journal workflows.
- Statement preview and export work without requiring a separate saved statement workflow.
- Statement totals reconcile to underlying posted/synced activity.
- Pending-sync items are available in a separate report.
- Tests cover statement period filtering, owner/property scoping, contribution/distribution treatment, sync inclusion rules, and pending-sync visibility.

## Docker/Manual Checks

- Run tests inside Docker.
- Create owner/property activity across a statement period.
- Generate an owner statement preview and export.
- Verify synced items appear in official totals.
- Verify pending-sync items appear only in the pending-sync report.

## Roadmap

Planned follow-on improvements after the Epic 7 baseline:

- add statement drill-down lines that link each summary row back to the source records that produced it;
- add a dedicated owner-activity detail action for manual sync/retry from the record detail page;
- expand the pending-sync report so it groups items by source type and exposes the sync failure reason inline where available.
