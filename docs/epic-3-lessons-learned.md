# Epic 3 Lessons Learned

This note captures the practical workflow decisions and implementation constraints that emerged while finishing Epic 3, so a future developer or agent can continue the rent-roll and charge workflow without relearning the same boundaries.

## What Epic 3 Taught Us

- Lease-driven charges are simpler and safer than splitting scope across property, unit, tenant, and lease fields in the UI.
- The lease already carries the full charge context, so the form should infer `property`, `unit`, and `tenant` from the selected lease.
- Charge approval is easier to use when it happens from the charge dashboard itself instead of forcing the user into an edit screen.
- Bulk actions are a better fit than per-row approve controls once the charge list starts carrying operational work.
- Bulk approve and bulk archive should live behind the same list view so the UI and server-side action logic stay aligned.
- Flash messages are important for bulk actions because the result is not obvious after the page redirects.
- Charge approval must continue to flow through `TenantChargeService.approve_charge`; do not shortcut around the service layer just because the UI is simpler.
- Synced charges should keep the narrow edit rule: only `due_date` and `description` remain editable after sync.

## What We Should Keep Doing

- Keep the charge create flow lease-first.
- Auto-populate scope fields from the lease instead of asking the user to repeat the same data.
- Use one bulk-action form on the charge list for approve/archive workflows.
- Keep the action vocabulary small and explicit.
- Reuse the same server-side approval path for single and bulk operations.
- Keep tests focused on the actual user path, including the list page, selected rows, and redirect feedback.
- Run the Epic 3 test slice in Docker, not against host Python.

## What To Avoid Next Time

- Avoid reintroducing separate property, unit, and tenant inputs on the charge form when the lease is the authoritative scope source.
- Avoid adding a separate approval confirmation page unless there is a strong accounting reason to do so.
- Avoid row-level approve buttons once bulk selection exists.
- Avoid direct status mutation in views when the service layer already owns the workflow transition.
- Avoid letting the dashboard and tests drift apart from the supported bulk-action vocabulary.

## Epic 3 Follow-On Guidance

For the next change in this area, start by writing down:

- whether the workflow is lease-scoped only or needs a separate property-level manual-charge path;
- which charge statuses are allowed to transition through bulk action;
- whether bulk archive should archive synced charges or preserve synced history separately;
- which user-facing confirmation or messaging is needed after a bulk action;
- which tests prove the list view, bulk POST handler, and sync behavior still match the intended workflow.

If a future feature needs property-level manual charges again, add that as a separate, explicit workflow rather than weakening the lease-driven charge form.
