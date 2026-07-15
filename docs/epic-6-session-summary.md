# Epic 6 Session Summary

## What We Decided

- Epic 6 scope for this pass: MVP banking and reconciliation visibility only
- Reconciliation scope: visibility only
- Missing LedgerOS banking API handling: add the narrow API only if a required surface is absent
- Deposit and withdrawal payloads: whatever LedgerOS already exposes
- Check writing: deferred unless explicitly expanded later
- No LedgerOS code change was required for the MVP visibility pass

## What We Verified

- The sibling `ledgeros_v2` repo already exposes the needed banking endpoints:
  - `GET /api/v1/bank-accounts/`
  - `GET /api/v1/bank-reconciliations/`
  - `POST /api/v1/bank-deposits/`
  - `POST /api/v1/bank-withdrawals/`
- PropertyLedger now consumes the existing read endpoints for banking visibility
- The new banking page is read-only and protected behind login
- The implementation passed targeted Docker-based tests

## What Changed

- Added a LedgerOS banking read client in `payments/services.py`
- Added a banking visibility page at `payments/banking/`
- Wired the new page into the Payments app and global navigation
- Added tests for the banking read client and the visibility page
- Updated the Epic 6 documentation in `docs/`

## Documentation Captured

- [Epic 6 runbook](epic-6.md)
- [Epic 6 implementation epic section](propertyledger-implementation-epics.md)

## Verification

Targeted test slice:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test payments.tests.test_banking_visibility
```

Result:

- passed

## Remaining Follow-Up

- Unreconciled activity visibility is still a future enhancement
- Check writing remains deferred from this MVP pass
