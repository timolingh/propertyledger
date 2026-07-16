# Epic 2 Lessons Learned

This note captures the setup, CRUD, and workflow lessons from Epic 2 so later epics can reuse them without rediscovering the same UX and workflow gaps.

## What Made Epic 2 Easier

- A dependency-aware setup order worked better than a generic wizard for this scope.
- The app stayed easier to use when the UI pointed users to the next required record type.
- Matching the admin surface to the app surface reduced confusion.
- Calendar date inputs improved lease entry without adding workflow complexity.
- Docker-only verification kept the repo workflow consistent across macOS and Linux.

## What We Should Keep Doing

- Keep one explicit setup path and document the order of operations.
- Gate create screens when a required parent record does not exist yet.
- Prefer small, concrete UX cues over broad speculative configuration.
- Keep admin labels, app labels, and docs aligned.
- Use real browser-friendly input widgets for date-heavy forms.
- Run automated checks in Docker and document that at the repo level.

## What To Avoid Next Time

- Avoid adding a wizard when a clear ordered flow is enough.
- Avoid forcing repetitive master-data entry one record at a time when a bulk load path is likely needed.
- Avoid letting admin defaults leak into the user-facing model labels.
- Avoid document paths or test commands that only work in one OS environment.

## Follow-On Guidance

For the next epic, start by writing down:

- the required setup order;
- any create screens that need parent records first;
- which workflows need bulk import or bulk load support;
- which date or status fields need specialized widgets or guardrails;
- which checks must run in Docker.

