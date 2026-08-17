# Session Notes

Last updated: August 14, 2026

## What We Covered

- Reviewed the repo docs with a focus on beta onboarding and setup clarity.
- Confirmed the beta scripts and setup flow were not leaving the demo in a fully ready state.
- Identified that the setup screen was confusing because it mixed:
  - LedgerOS connection settings
  - selected LedgerOS entity/accounting period
  - account mappings
  - smoke/setup status
- Agreed on the repo-wide philosophy that user feature testing should happen only after setup is correct.

## Docs Updated

- Added a new admin setup guide:
  - [`docs/admin-setup.md`](./docs/admin-setup.md)
- Updated quick start to state that setup is a prerequisite for a usable environment:
  - [`docs/quick-start.md`](./docs/quick-start.md)
- Updated beta testing docs to say admin setup must be completed before beta testing:
  - [`docs/beta-testing.md`](./docs/beta-testing.md)
- Updated the README docs index to include the new admin setup guide:
  - [`README.md`](./README.md)

## Guidance Added To CLAUDE.md

- Added a repo-level principle:
  - user-facing feature testing should happen after the relevant setup path is correct
  - configuration should be automated or documented before testing the feature

## Setup Screen Clarity Work

- Clarified the setup screen wording so it explains the difference between:
  - `LedgerOS Connection`
  - `Selected LedgerOS Books`
  - account mappings
  - setup/smoke status
- Added explanatory copy to:
  - [`ledgeros/templates/ledgeros/setup.html`](./ledgeros/templates/ledgeros/setup.html)
  - [`ledgeros/templates/ledgeros/base.html`](./ledgeros/templates/ledgeros/base.html)
- Added/updated tests to lock the wording in place:
  - [`ledgeros/tests/test_models_and_api.py`](./ledgeros/tests/test_models_and_api.py)

## Beta Setup Flow Fixes

- Updated `scripts/beta-seed.sh` so it now:
  - bootstraps the selected LedgerOS entity and accounting period into PropertyLedger
  - seeds the beta demo data
  - runs the setup smoke step so the demo is recorded as ready when checks pass
- Updated `scripts/beta-reset.sh` and `scripts/beta-seed.sh` to print clearer next-step instructions and URLs.

## Smoke Status Fix

- Discovered that `make smoke` previously verified setup but did not persist the smoke result back to the setup model.
- Fixed that by adding a shared recording path:
  - new command: [`ledgeros/management/commands/run_setup_smoke.py`](./ledgeros/management/commands/run_setup_smoke.py)
  - shared service logic in [`ledgeros/services.py`](./ledgeros/services.py)
- Wired both workflows to use it:
  - `make smoke`
  - setup-page `Run setup smoke` button
- The setup page now records smoke status and can mark setup complete when all checks pass.

## Tests Run

- Ran focused Docker-based Django tests successfully.
- Verified:
  - beta bootstrap commands
  - setup selection bootstrap
  - setup-page smoke action
  - new smoke-recording command

## Important Current State

- The beta demo setup should now be much closer to “ready before testing.”
- `make smoke` now records its result on `PropertyLedgerSetup`.
- The setup page has a `Run setup smoke` button that does the same.
- The docs now state that setup is a prerequisite for both quick start and beta testing.

## Good Next Steps

1. Review the `/home` landing page, which still feels too much like a todo list.
2. If needed, refine the admin setup guide into a shorter operator checklist.
3. Re-run the beta flow end-to-end and confirm the first setup page now reads as understandable to a new admin.

## Follow-Up Session Summary

- Investigated why `scripts/beta-seed.sh` was not finishing when LedgerOS web was not running.
- Updated `scripts/beta-seed.sh` so the final smoke step is best-effort:
  - it records smoke when LedgerOS web is reachable
  - it warns and exits successfully when LedgerOS web is still down
- Aligned the docs with that behavior:
  - [`docs/admin-setup.md`](./docs/admin-setup.md)
  - [`docs/beta-testing.md`](./docs/beta-testing.md)
  - [`docs/quick-start.md`](./docs/quick-start.md)
- Clarified the setup wording so the docs emphasize selected books and smoke timing rather than creating friction around beta startup.
- Briefly removed the LedgerOS entity check from the setup UI and validation, then reverted the repo to `ac1be96a95f25c663bac1514fd9ddb830f92bc1a` at the user's request.
- Re-applied only the beta-seed non-blocking smoke behavior and the matching docs updates after the revert.

## Invoice Lifecycle Session Notes

This session clarified the tenant invoice lifecycle. In the current codebase, the UI calls these records "invoices," but the underlying model is `TenantCharge`.

### State Diagram

```text
Draft
  | create/save as a normal charge
  v
Approved
  | approve_charge()
  | create or reuse LedgerOSSyncRecord
  v
Sync Pending
  | POST /api/v1/invoices/ to LedgerOS
  | success
  v
Synced
  | posted accounting state
  | limited post-sync edits only
  |
  | sync error or transport/validation failure
  v
Sync Failed

Any non-voided state
  | archive single record or bulk archive
  v
Voided
```

### Detailed Transition Notes

- `draft` is the initial state for a new tenant charge.
- Draft charges may be edited normally.
- Lease-scoped charges can be created from a lease and auto-fill property, unit, and tenant.
- Base rent charges are generated as drafts from active leases and are unique per lease and billing period.
- The `approved` state is the trigger for posting the charge to LedgerOS.
- `approve_charge()` is the service boundary that owns the transition from draft into the sync flow.
- When approval starts, the code creates a `LedgerOSSyncRecord` if one does not already exist.
- The sync record is moved to `in_progress`, and the charge is moved to `sync_pending`.
- The charge is then posted to LedgerOS through `POST /api/v1/invoices/`.
- If LedgerOS accepts the request, the sync record becomes `succeeded` and the charge becomes `synced`.
- If the posting fails, the sync record becomes `failed` and the charge becomes `sync_failed`.
- `synced` charges are treated as posted accounting history.
- After sync, the form disables every field except `due_date` and `description`.
- `voided` is the archive state used by single-record archive and bulk archive actions.
- Bulk approve skips already finalized records such as `synced` and `voided`.
- Bulk archive sets charges to `voided` without attempting a LedgerOS posting action.

### Identity and Posting Notes

- The public-facing UI and docs often refer to this workflow as invoices.
- The actual accounting handoff uses a stable external invoice number such as `tenant-charge:{pk}`.
- The LedgerOS invoice payload uses the tenant-specific customer code `tenant-{tenant.pk}`.
- The invoice posts a line to rental income using the configured rental income account mapping.
- The sync record stores the LedgerOS resource id, journal entry id when available, request hash, and response payload.

### Practical Meaning

- `draft` means local only.
- `approved` means ready to post and entering the sync pipeline.
- `sync_pending` means the system is actively trying to post the invoice.
- `synced` means LedgerOS accepted the invoice and PropertyLedger now treats it as posted history.
- `sync_failed` means the posting did not complete and needs a retry or fix.
- `voided` means the invoice is archived and should no longer be treated as active workflow state.
