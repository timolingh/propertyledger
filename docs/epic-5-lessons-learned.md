# Epic 5 Lessons Learned

This note captures the practical workflow, mapping, and sync issues that surfaced while finishing Epic 5 so the next accounting epic can start from a more complete checklist.

## What Epic 5 Taught Us

- Small setup gaps can break the whole accounting flow even when the main feature code is correct.
- Credit-card and debt-service workflows need their liability accounts, account mappings, and bootstrap data verified up front.
- A generic sync-event bridge is useful, but the payload still has to match LedgerOS account availability exactly.
- The user-facing flow should make the accounting intent obvious; hidden flags and implicit fields are easy to miss.
- Bootstrap data, sample chart data, and runtime validation need to stay aligned so new installs and existing databases behave the same way.
- A workflow that looks simple in the UI can still span multiple subsystems, so the decision log has to call out every required account and mapping.

## What We Should Keep Doing

- Keep the required account list explicit before coding a new accounting workflow.
- Keep bootstrap/sample-chart data in sync with the app’s runtime expectations.
- Keep the UI language aligned with the actual accounting treatment.
- Keep test coverage focused on end-to-end setup, not just the happy-path sync payload.
- Keep setup guidance in the docs concrete enough that a user can reproduce the flow without guessing.

## What To Avoid Next Time

- Avoid assuming a liability account will already exist just because the workflow references it.
- Avoid burying key accounting choices behind a generic form field if the user needs a distinct workflow.
- Avoid treating seeded mappings as sufficient unless the underlying LedgerOS chart has been verified too.
- Avoid calling an epic done until the bootstrap, UI, sync payloads, and docs all agree on the same account names and codes.
- Avoid leaving users to discover missing prerequisite accounts through a failed posting attempt.
