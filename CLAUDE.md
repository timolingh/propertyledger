## Project-Specific Guidelines: PropertyLedger

PropertyLedger is a real estate accounting client built on top of LedgerOS.

This system handles real estate accounting workflows. Treat accounting behavior as high-risk.

Before coding:
- State domain assumptions explicitly.
- Identify whether the change affects LedgerOS sync, ledger entries, reports, balances, payments, invoices, bills, reconciliations, taxes, owner statements, tenant ledgers, property/unit reporting, or audit trails.
- If accounting treatment is ambiguous, stop and ask.
- Before changing accounting behavior, read `docs/technical-manual.md` and the archived docs in `docs/archive/` only when historical context is needed. Keep code, tests, and docs aligned.

Simplicity:
- Prefer explicit domain functions over generalized abstractions.
- Do not create a generic property-management platform unless multiple concrete use cases already require it.
- Avoid speculative configurability.

Surgical changes:
- Every changed line must trace to the requested behavior.
- Do not refactor unrelated property, payment, reporting, LedgerOS adapter, or accounting-sync code.
- Do not rename accounts, enums, statuses, event types, or transaction types without migration and test coverage.
- In markdown docs, use repo-relative links for files and paths. Do not introduce machine-specific absolute paths such as `/Users/...` or `/home/...`.
- When updating doc hyperlinks, keep them portable across macOS and Linux.

Goal-driven execution:
- For every accounting or property-accounting change, define success using examples:
  - expected LedgerOS sync request
  - expected journal/accounting treatment in LedgerOS
  - expected account balances
  - expected owner statement line items
  - expected tenant ledger entries
  - expected property/unit report totals
  - expected sync status and retry/idempotency behavior
- Write or update tests before implementation when behavior changes.

## Epic Implementation Discipline

Before implementing or reviewing any epic, read and follow:

- `docs/technical-manual.md`
- `docs/user-manual.md` when the work affects user flows
- `docs/quick-start.md` when the work affects setup or smoke checks
- archived docs in `docs/archive/` when you need historical implementation context

Every change should still have clear traceability, explicit deferred/out-of-scope items, automated tests for implemented property/accounting invariants, and Docker-ready manual acceptance checks. Keep the active documentation set consolidated instead of recreating one-off epic runbooks.

## LedgerOS Boundary Discipline

PropertyLedger must remain a separate application from LedgerOS.

Local setup and Make targets only manage PropertyLedger containers and local bootstrap rows. LedgerOS is assumed to be running at a separate endpoint.

PropertyLedger owns:
- properties
- units
- owners
- tenants
- leases
- rent roll
- property/unit attribution
- owner statements
- maintenance expense context
- local workflow status
- LedgerOS sync mappings

LedgerOS owns:
- chart of accounts
- accounting periods
- invoices
- bills
- payments
- journal entries
- banking/reconciliation records
- accounting reports
- audit trail
- accounting invariants

PropertyLedger must interact with LedgerOS through a controlled adapter/API boundary.

Do not:
- write directly to the LedgerOS database;
- import LedgerOS Django models into PropertyLedger domain code;
- bypass LedgerOS APIs/services for accounting mutations;
- assume PropertyLedger local records are posted accounting facts until LedgerOS sync succeeds.

When PropertyLedger is the active context, keep LedgerOS setup and bootstrap flows inside PropertyLedger where possible. Do not force the user to switch to the LedgerOS repo or UI to complete configuration that PropertyLedger already knows it needs; use LedgerOS APIs or supported commands from the PropertyLedger-side bootstrap instead.

## Anti-Slop Engineering Principles

1. **Run the code, not just the generator.**  
   Generated code is not complete until the relevant runtime checks pass. For Django work, at minimum run `./scripts/check.sh` or its equivalent commands: `python manage.py check`, `python manage.py makemigrations --check --dry-run`, migrations, relevant management commands, and tests before claiming the task is done.
   Always run those checks inside the containerized app environment, not against host Python.

2. **Use the dev bootstrap script for local setup.**  
   When you need the PropertyLedger environment prepared end to end, use `./scripts/dev-bootstrap.sh` or `make dev-bootstrap`. The script should source or receive `LEDGEROS_BASE_URL`, `LEDGEROS_CLIENT_ID`, and `LEDGEROS_HMAC_SECRET`, which come from the running LedgerOS endpoint and its API client configuration.

3. **Preserve domain invariants in executable tests.**  
   Any business rule described in the PRD or epic must have a corresponding test. For PropertyLedger, this includes rent-generation idempotency, tenant ledger accuracy, property/unit attribution, owner statement totals, LedgerOS sync idempotency, posted/synced status handling, and clear separation between draft/unsynced operational records and posted LedgerOS records.

4. **Do not bypass the service/adapter layer for state-changing operations.**  
   Views, serializers, admin actions, management commands, background jobs, and future integrations must call domain services for mutations. Accounting mutations must go through the LedgerOS adapter/API boundary. They must not directly change critical fields such as sync status, posted timestamps, LedgerOS resource IDs, reconciliation links, or audit records.
   - Web UI, API, admin, and management commands must share the same application write path for the same property-accounting behavior.
   - If a state-changing action exists in the API, the UI/admin path must invoke the same service entrypoint rather than reimplementing the mutation or editing model fields directly.
   - Read-only convenience fields may differ by surface, but the underlying property/accounting transition must remain one service call.

5. **Avoid polished scaffolds that are not wired together.**  
   New files must be internally consistent across imports, model fields, admin config, serializers, migrations, URLs, tests, commands, and adapter calls. If a symbol is referenced, it must exist. If a field is renamed, every caller must be updated. No handoff should rely on the user discovering integration errors.

6. **Separate implemented scope from future scope.**  
   Follow the approved PRD/epic boundary. Do not implement later-epic features early just because they are easy to scaffold. If a future hook is needed, keep it minimal, documented, and covered by tests without pretending the later feature is complete.

7. **Keep command naming canonical unless there is a real workflow distinction.**  
   Use the shortest documented Make target names as the primary workflow in docs and examples. Only introduce a suffix like `-full` when it represents a distinct supported path and the docs explain why both names exist. If a new name is only an alias, label it explicitly as such.
