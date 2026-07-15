# Epic 8 Runbook

## Purpose

This document captures the agreed scope and decision log for Epic 8 in PropertyLedger.

Epic 8 adds the PropertyLedger `reports` app as the home for:

- interactive PropertyLedger reports;
- in-page LedgerOS report rendering;
- a reports landing page inside PropertyLedger;
- a separate read-only owner statement report entry point that points back to Epic 7 for preview/export;
- a pending-sync report for statement-related items that are not yet synced.

Epic 8 does not add:

- a CSV export flow for the new reports;
- an arbitrary report builder;
- a SQL report builder;
- a dedicated drill-down workflow;
- a custom dashboard designer.

## Decision Log

The following decisions are now fixed for Epic 8:

1. Reports live in a dedicated `reports` app inside PropertyLedger.
2. Epic 8 includes all reports in the MVP report set, not just a subset.
3. Reports are interactive only for now; CSV export is roadmap scope.
4. LedgerOS reports are rendered inside PropertyLedger.
5. Owner statement reporting remains a separate entry point from Epic 7.
6. Drill-down is deferred to a later epic.

## Report Definition Table

| Report | Source records | Period/date basis | Scope filters | Draft / unsynced handling | Reconciliation / drill-down |
| --- | --- | --- | --- | --- | --- |
| Rent roll | PropertyLedger leases, units, tenants, properties | As of date | Property | Excludes non-synced lease state from statement-style totals; report is operational | Drill-down deferred; report shows source rows only |
| Tenant ledger | Synced tenant charges and payments | Period start / end | Property, tenant | Excludes voided and unsynced activity | Drill-down deferred; report shows source rows only |
| Delinquency | Synced tenant charges and applied payments | As of date | Property | Excludes voided and unsynced activity | Drill-down deferred; report shows delinquent source rows |
| Property income / expense | Synced tenant charges, payments, and vendor bills | Period start / end | Property | Excludes unsynced activity from totals | Reconciles to posted/synced activity; drill-down deferred |
| Owner statement report | Synced owner activity, synced tenant charges/payments, synced bills, synced deposits | Preset month, quarter, year, or custom range | Owner + property | Official totals include synced items only | Separate Epic 7 statement entry point remains authoritative; drill-down deferred |
| Security deposit ledger | Synced security deposit events | Period start / end | Property, tenant | Excludes unsynced activity | Drill-down deferred |
| Management fee expense summary | Synced vendor bills | Period start / end | Property | Excludes unsynced activity | Drill-down deferred |
| Maintenance expense summary | Synced vendor bills | Period start / end | Property | Excludes unsynced activity | Drill-down deferred |
| LedgerOS trial balance | LedgerOS API | Period start / end | None beyond date bounds | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS profit and loss | LedgerOS API | Period start / end | None beyond date bounds | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS balance sheet | LedgerOS API | Period start / end | None beyond date bounds | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS period summary | LedgerOS API | Period start / end | None beyond date bounds | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS tax summary | LedgerOS API | Period start / end | None beyond date bounds | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS chart of accounts | LedgerOS API | No period required | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS invoice status | LedgerOS API | Period start / end when available | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS bill status | LedgerOS API | Period start / end when available | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS payment status | LedgerOS API | Period start / end when available | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS bank balances | LedgerOS API | As of / current view when available | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS reconciliation status | LedgerOS API | Period or current status view when available | None | LedgerOS data only, read-only | No custom drill-down in Epic 8 |
| LedgerOS audit drilldown | LedgerOS API | When available | None | LedgerOS data only, read-only | Deferred drill-down behavior remains in LedgerOS output |

## In Scope

- `reports` app landing page;
- PropertyLedger report pages;
- LedgerOS report pages rendered in PropertyLedger;
- owner statement report link that points back to Epic 7;
- pending-sync report for statement-related items;
- property-management reports that reconcile to synced records only;
- report forms that default to interactive in-page filtering.

## Out of Scope

- arbitrary report builder;
- SQL report builder;
- CSV export for the new report pages;
- custom dashboard designer;
- dedicated drill-down flow;
- cash-basis owner statements;
- advanced tax reporting.

## Roadmap

The following items are intentionally deferred and should be treated as follow-on work, not Epic 8 scope:

- CSV export for PropertyLedger report pages;
- row-level drill-down from report totals into source records;
- richer report dashboards or saved report views;
- custom report composition / builder tooling;
- expanded LedgerOS audit and accounting drill paths beyond the read-only pages exposed here.

## Acceptance Criteria

- PropertyLedger reports are accessible from the main reports landing page.
- PropertyLedger report pages render interactively inside PropertyLedger.
- LedgerOS accounting reports render in-page through the LedgerOS API.
- Official totals exclude draft and unsynced activity.
- Owner statement reporting remains linked to the Epic 7 statement workflow.
- A pending-sync report exists for items that have not yet synced.
- Tests cover the report landing page, report filters, and LedgerOS report rendering.

## Docker / Manual Checks

- Run tests inside Docker.
- Open the reports landing page and verify the PropertyLedger and LedgerOS report groups.
- Open at least one PropertyLedger report and one LedgerOS report.
- Verify the owner statement report links to the Epic 7 statement page.
- Verify the pending-sync report only shows unsynced items.
