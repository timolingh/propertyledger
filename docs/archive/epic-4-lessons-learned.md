# Epic 4 Lessons Learned

This note captures the practical workflow and accounting boundaries that emerged while finishing Epic 4, so Epic 5 can start with the right decision log instead of relearning the same sync and status rules.

## What Epic 4 Taught Us

- Tenant payments and security deposits are accounting workflows, not just audit events.
- A successful sync must mean LedgerOS has posted the accounting effect, not merely recorded a handoff record.
- The local record and the sync status need to stay separate so drafts, retries, and failed handoffs can be handled safely.
- Synced payment and deposit records should be treated as immutable except for clearly non-accounting note fields.
- Payment application rules need to stay deterministic so partial payments and overpayments do not drift across invoice types.
- Security deposit balance should continue to be derived from event records rather than maintained as a loose manual total.
- The generic sync-event envelope is useful as a boundary, but it still has to map to a real posted LedgerOS action on the other side.
- Docker-only tests and smoke checks kept the workflow reproducible and should stay the default.
- There is no real substitute for the actual LedgerOS contract when verifying accounting behavior; an in-process stub can help tests, but it does not replace the real posting rule.

## What We Should Keep Doing

- Keep the sync boundary explicit: local business data stays in PropertyLedger, posted accounting facts stay in LedgerOS.
- Keep local statuses, sync statuses, and setup statuses separate.
- Keep edit rules narrow after sync so bookkeeping history stays trustworthy.
- Keep payment-application ordering deterministic and documented.
- Keep security deposit balances derived from events and validate them against the event stream.
- Keep the test suite focused on the user path, the sync handoff, and the resulting posted-accounting behavior.
- Keep all automated checks inside Docker so the repo stays portable.

## What To Avoid Next Time

- Avoid treating a sync log entry as proof of posting.
- Avoid adding broad edit access to synced records just to make the UI simpler.
- Avoid mixing setup completion with accounting sync success.
- Avoid letting a payment or deposit workflow fall back to journal-only behavior unless the epic explicitly says that is acceptable.
- Avoid adding a new local status without defining how it differs from sync status and from setup status.
- Avoid designing a workflow without a retry and duplicate-handling story for the LedgerOS-bound event.

## Epic 5 Preflight Guidance

Before coding Epic 5, write down these decisions first:

- vendor bill statuses and vendor payment statuses, including which ones are local-only and which ones reflect LedgerOS posting;
- whether bill approval exists at all, or whether Epic 5 stays draft-to-sync without a separate approval step;
- the credit-card liability and AP-clearing treatment for card-paid vendor bills;
- the debt-service payment split rules for principal and interest;
- the required account mappings and what happens when one is missing or inactive;
- which LedgerOS endpoint or resource each vendor-bill, vendor-payment, credit-card-payoff, and debt-service event uses;
- the idempotency and retry keys for each accounting-bound event;
- the edit rules after sync for bills, payments, and maintenance records;
- whether maintenance records are source documents, reporting dimensions, or both.

If any of those items are still ambiguous, stop and resolve them before implementation begins. Epic 5 will be much safer if the accounting treatment is explicit up front.
