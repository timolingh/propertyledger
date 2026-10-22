# Workflow revamp: discovery and implementation plan

Date: October 21, 2026. Status: discovery complete; WP0 through WP4 complete; WP5–WP6 proposed.

Scope authority: [Workflow Home PRD v1.0](PropertyLedger_Workflow_Home_PRD_v1.0.md), especially approved Q1–Q16 and the implementation gates in §14. This plan preserves those product choices. Historical epics are context, not the current scope.

## Baseline and boundaries

- PropertyLedger branch: `workflow_prd`; commit `d120ebda260d7e7bdcdb7f5dc3ab0eb2a6ecf9f4`. Working tree was clean before this document.
- Sibling LedgerOS source inspected read-only at `../ledgeros_v2`, commit `738ee0127df473a8ad0d54871ea554e938626c25`; its working tree was clean. This identifies inspected source, not the version deployed at the configured endpoint.
- Discovery included models, migrations, routes, views, forms, admin, services, permission/bootstrap helpers, shared templates, reports, and the existing tests.
- No application behavior, schema, accounting records, or sibling source changed during discovery.
- All accounting mutations stay behind PropertyLedger services and the LedgerOS HTTP adapter. No cross-repository ORM imports or database writes.
- Amounts remain decimal with two places in the existing single-currency, one-entity model. Existing accounting identifiers and status values remain intact.
- Payments record externally executed transactions. No payment rails, payment scheduling, tenant portal, automatic posting queue, or check printing is added.

## Verified differences from the target

| Area | Code evidence | Required change |
| --- | --- | --- |
| Shared home | `propertyledger/views.py:AppHomeRedirectView`, `ledgeros/navigation.py:get_home_redirect_url` route admins to Setup and others to role destinations. | Render one shared home; retain login destination and existing deep links. |
| Navigation | `ledgeros/templates/ledgeros/base.html` has unfiltered horizontal links, including Setup/Admin; Maintenance opens categories. | Shared responsive sidebar with capability-aware destinations and a distinct request queue. |
| Context reads | `LedgerOSAppContextMixin` repeatedly calls singleton `.load()`, whose implementation uses `get_or_create`. | New home context must use read-only queries, avoid implicit bootstrap on GET, and check health once per request. |
| Role enforcement | `ledgeros/roles.py:user_has_any_role` returns true when a user has no recognized role. | New capabilities deny unassigned/inactive users. Replace the permissive role fallback with explicit access rules and update fixtures that relied on it. Inventory existing users before rollout. |
| Read versus write | `payments/views.py:VendorBillDetailView.post` can call `sync_bill` under a reporting-role mixin without a separate write check. | Enforce actor authorization in the service and POST path. Add direct POST denial tests, including viewers. |
| Vendor bills | `VendorBill` has posting status only; `VendorBillService.save_and_sync_bill` immediately attempts posting when prerequisites exist. | Add independent submission/approval audit and explicit save-draft/submit actions; keep approval, posting, and payable status distinct. |
| Payment authority | Bill pay and retry views check bookkeeper/admin roles. `VendorPaymentService` takes no actor; generic create/update/sync paths remain available. | Require separately granted per-user payment authority at every settlement entry point, including services and admin. |
| Payment safety to retain | `pay_bill` persists a unique submission UUID and fingerprint before external posting; `sync_payment` locks the payment; upstream balances validate new payments. | Preserve these identities, locks, CSRF/signed tokens, partial payments, and timeout replay behavior. |
| Maintenance | `MaintenanceCategory` and an expense summary exist; no request, lifecycle, attachments, or request/bill link. | Add requests, actor-attributed transitions, independent financial summaries, and an optional request reference on bills. |
| Receipt finalization | `TenantPaymentService.sync_payment` requires invoice applications covering the whole receipt. It creates a local `tenant_payment.finalized` summary without another cash posting. | Extend allocation/finalization to deposit portions without posting the full receipt a second time. |
| Deposit posting | `_security_deposit_event_details` contains context and amount but no `accounting_entries`. `sync_security_deposit_event` accepts a response without a posted journal. | Establish and prove explicit deposit journal treatment; stop treating an audit-only response as confirmed accounting. Historical rows require reconciliation, not automatic replay. |
| Reports | `OwnerStatementService` and `PropertyReportService` use the whole successfully finalized `TenantPayment.amount` for rent collection/tenant settlement. | A mixed receipt cannot use the parent amount for rent/AR totals. Separate confirmed invoice allocations from confirmed deposit activity; handle partial posting explicitly. |
| Admin writes | Vendor admin calls its service, but bill/payment/deposit admins mostly use default model saving; editable lifecycle fields are exposed on several forms. | Route affected writes through authorized services; make system-managed fields read-only and prohibit forged posted/approved states and destructive deletion of history. |
| Public API | `LedgerOSSyncEventCreateAPIView` creates local pending sync metadata; it does not dispatch approval/payment services. No dedicated external authentication layer is configured. | Do not route new financial mutations through this endpoint or count its pending rows as posted. New workflow endpoints are authenticated internal pages; new public mutation APIs are out of scope. |
| Baseline checks | Missing `LedgerOSConnectionSettings` Meta-options migration; no `scripts/check.sh` exists. | Add the metadata migration as a small prerequisite; use the actual Make/Docker commands. |

## Proposed answers to PRD §14

These are implementation proposals grounded in the checkout. Contract proof and runtime acceptance remain required where stated.

### Authorization and approval

Use a small per-user `WorkflowAuthorization` model in `payments/models.py`, with independent bill-approval and vendor-payment grants. Missing row means neither grant. Require an active, explicitly assigned staff workflow role as well as the relevant grant. Do not use Django superuser permission bypass as an implicit economic approval/payment grant. Admins, including superusers, may administer grants, but need their own explicit grants to approve/pay and may never self-approve.

Grant changes and bill decisions go through services that record actor, timestamp, old/new values and source in the immutable audit log. Recheck capabilities from current database state inside writes; do not trust cached template decisions. Migration creates no blanket grants. Bootstrap may grant named demo users only through the same audited service with an identified administrator; no production user receives silent authorization.

Proposed matrix:

| Action | Admin | Property manager | Bookkeeper | Owner viewer | Read-only viewer | Unassigned |
| --- | --- | --- | --- | --- | --- | --- |
| Shared home | Yes | Yes | Yes | Yes | Yes | Yes, access guidance only |
| Existing record/report reads | Existing authorized scope | Existing authorized scope | Existing authorized scope | Existing report scope | Existing authorized scope | No sensitive queues |
| Create/edit/submit vendor bills | Yes | No, retain current boundary | Yes | No | No | No |
| Approve/reject vendor bills | Explicit grant; different submitter | Explicit grant; different submitter | Explicit grant; different submitter | No | No | No |
| Record/retry vendor settlement | Explicit grant | Explicit grant | Explicit grant | No | No | No |
| Create/triage/assign/verify/close/reopen maintenance; link bills | Yes | Yes | Yes | No | No | No |
| View maintenance details | Yes | Yes | Yes | No additional access | Yes | No |
| Administer grants/setup | Yes | No | No | No | No | No |

An individually granted manager can approve/pay an existing bill without gaining unrelated accounting/configuration rights. Creating a bill from maintenance still requires bill-creation authority; managers can link an existing compatible bill. All users see recognizable workflow cards; viewers receive authorized read actions rather than write-only dead ends. Owner viewer is not a new owner portal and gains no inferred ownership scoping.

Approval has a separate state: draft, submitted, approved, rejected, withdrawn, or legacy approval not recorded. Persist submitter, submission time/version, approved financial fingerprint, decision actor/time/reason, and immutable decision history. Lock the bill during transitions and payment authorization. Material local edits invalidate approval before another payment; submitted versions cannot change underneath an approver. Already-posted economic fields remain immutable. Notes can remain editable without reapproval when excluded explicitly from the financial fingerprint.

Prefer explicit draft → submit → independent approval → explicit LedgerOS posting → payment for new bills. This avoids posting rejected bills and makes offline drafts useful. Existing posted bills retain their accounting status and can be submitted for prospective payment approval without reposting. Posting retries of already attempted bills retain their original payload/identity; do not reinterpret an uncertain attempt as an editable draft. This deliberately replaces auto-post-on-save for new bills, as required by the PRD's draft/submit journey.

Keep posted legacy payments intact and label missing historical approval accurately. Existing unpaid posted bills need a real new approval before new settlement; migration must not invent a historical submitter or decision. A designated user explicitly submits a legacy bill for prospective approval, then another designated approver decides. Already attempted payments need a distinct reconciliation path: resolve the original operation with its original key, never authorize a replacement payment to recover a timeout. If authorization was revoked, an authorized operator resumes the same saved operation. Do not block identification of a previously committed payment solely because the fresh balance is now zero.

Credit-card bill settlements require the new payment grant. Credit-card payoff (`VendorPayment.is_credit_card_payoff`) and `DebtServicePayment` remain separate existing accounting workflows; do not make a card payoff settle a bill again. The legacy card-link command remains a narrowly authorized reconciliation operation against a verified existing journal, with actor/provenance recorded, not a means to bypass new-payment approval.

### Maintenance and attachments

Keep maintenance in the existing `payments` app to reuse vendors/categories/bills without an app rename. Put lifecycle services/forms/views in focused new modules to avoid further expanding the existing large files.

`MaintenanceRequest` requires property, nonblank description, category and priority. Optional fields: unit, tenant, assigned vendor, target date, nonnegative decimal estimated cost. Store creator, origin/source metadata, status, verifier/time, closure data, and reopen history. Unit must belong to property; selected tenant must have a verifiable lease association to that property/unit. Allow property-wide requests without a unit. Record every transition and bill linkage with an actor. Use explicit allowed transitions, row locks and optimistic version checks for stale forms; no generic editable status field.

Canonical path: open → triaged → assigned → in progress → verified → closed. Permit documented hold/resume and cancellation transitions; reopening a closed request requires permission and a reason and returns it to triage while retaining closure history. Verification records who checked the work. Closure does not require a bill or payment. Closing with no bills records whether invoicing is pending or work had no external cost, so the queue can distinguish these cases.

Add a nullable protected maintenance-request FK on `VendorBill`: many bills/vendors per request; one request per bill. Validate property and optional unit compatibility. Linking/unlinking must be audited; never silently reattribute a posted bill. Create/link works at any request state, including closed. A signed submission UUID persisted before bill creation prevents duplicate bills on repeat submission. Opening a prefilled bill form creates nothing and posts nothing.

No attachment storage/validation configuration exists in the checkout. Proposed first implementation uses private filesystem storage with authenticated download, randomized names, a 5 MiB per-file limit, JPEG/PNG only, content decoding/re-encoding, stripped metadata, and no remote URL fetching or public media routes. A maintained image decoder dependency and persistent private storage deployment must be configured and verified before enabling uploads. If that cannot be established, ship no upload control and report photos as a release dependency; optional photos are not silently declared complete. Deployment storage/backup/access policy remains to be verified in WP3.

### Mixed receipt contract: financial implementation gate

Source findings in sibling LedgerOS:

- `apps/accounting/api/ingestion_serializers.py:ApiPaymentCreateSerializer` accepts invoice/bill payments, not mixed receipt/deposit allocations. Funding selection and existing-journal linking are bill-only.
- `apps/accounting/services/api_ingestion.py:submit_payment_event` posts an invoice payment to the LedgerOS default cash account, creating its payment/application and Cash/AR journal.
- `submit_sync_event` posts a generic journal only when `payload.accounting_entries` is supplied. Otherwise a deposit event can return an audit record with no journal.
- That generic journal uses `occurred_at.date()` as posting date; current PropertyLedger deposit envelopes use the local event creation time rather than the selected deposit event date.
- Existing tests demonstrate generic event idempotency and balanced journal creation separately, but do not establish an end-to-end mixed receipt contract.

Recommended candidate to prove before mutation code: retain `TenantPayment` as the economic receipt identity, existing invoice applications for rent, and add explicit receipt-owned deposit allocation lines referencing `SecurityDepositEvent`. Each component posts only its own amount, shares the stable local receipt reference, and has a persisted independent idempotency key. The parent remains a local summary with no cash journal. Do not change existing invoice-application keys. Deposit posting must use the receipt's payment date consistently in the supported event envelope.

| Component for a $2,000 receipt | LedgerOS request candidate | Required journal/result |
| --- | --- | --- |
| $1,500 rent | Existing invoice payment endpoint and original allocation identity | Debit Cash 1,500; credit AR 1,500; invoice balance falls by 1,500; posted payment/journal IDs |
| $500 refundable deposit | Generic event with explicit validated journal lines for this portion and stable receipt/allocation reference | Debit the same Cash account 500; credit configured deposit liability 500; posted journal ID/status |
| Parent finalization | Local confirmed-component summary only | No external write or additional Cash debit; sum confirmed allocations equals 2,000 |

Before selecting this mechanism, prove in an isolated LedgerOS sandbox that account selection matches the operating-bank mapping, dates/periods are correct, signed retries reuse the exact serialized payload, both component writes are idempotent after timeout, and deposit event references link unambiguously to the receipt. Assert aggregate Cash +2,000, AR −1,500 and deposit liability +500. A second finalize/retry must leave all balances and journal counts unchanged. The current invoice API's implicit cash selection is a compatibility condition, not permission to assume a match.

This candidate may work through current APIs; an upstream change is not yet proven necessary. If proof fails, propose the smallest explicit receipt-reference/funding or combined-receipt API extension. Do not bypass the adapter or implement mixed financial mutations while the gate is open. Other work packages can proceed.

Persist every component identity and frozen posting payload before its outbound request. Handle partial success without deleting/reallocating confirmed lines. Parent finalization requires every invoice and deposit line to return posted evidence. The receipt's allocation sum must exactly equal its positive total. Lock economic fields after any posting attempt, including timeouts. No automatic offline posting.

Existing deposit rows marked posted may be audit-only. Inventory and reconcile them read-only before deciding on corrective action. Do not add journal lines to old attempted payloads, rotate keys, automatically repost, or backfill fabricated posted evidence. Preserve original sync rows. Correction of uncertain historical deposits needs a separate evidence-backed reconciliation design.

Reports must derive invoice settlement/rent collection from confirmed rent allocations, never the whole mixed parent amount. Deposit components belong only to the deposit liability ledger. Confirmed components of partially failed receipts need explicit accounting visibility even while the parent remains incomplete. Update owner statements, tenant ledgers, delinquency and property cash summaries together; preserve a documented fallback for historic parent-only receipts with no allocation evidence, without double counting receipts that have allocations. A read-only history inventory must establish whether such records exist before choosing the fallback. Post-finalization refunds/reversals remain on existing explicit correction paths; a new combined correction UI is deferred.

### Queues, health and navigation

- Local queues: submitted bills the user may act on (exclude self-approval), unfinished receipts, and active maintenance requests. Staff can see only authorized scopes; do not imply ownership with a fabricated assignee filter.
- Verified requests awaiting invoices: verified/closed with invoice expected and no linked bill; internal/no-cost closures are excluded.
- Ready-to-pay bills: approved, posted and eligible according to current LedgerOS bill reads. On outage the result is unavailable, not an inferred local unpaid count. Query the same permission-filtered set used by the destination queue; paginate rows and do not label a page subtotal as a global total.
- Pending payment confirmations are saved attempted operations, not fresh payment invitations. Distinguish these from local unattempted drafts.
- Reuse batched `BillPaymentStatusService` reads (100 references per request); avoid per-card/per-row network calls. Begin with bounded, paginated detail queues; measure large-portfolio count performance before claiming global live metrics. Initial performance target: local home rendering under 500 ms excluding upstream calls, with one health probe and a bounded upstream timeout; verify against representative data.
- Use read-only home context rather than `.load()`/bootstrap helpers. Missing setup yields a clear readiness banner. Service readiness/permission/connection errors must be distinct, and health success alone never authorizes a posting.
- Setup remains directly reachable at its existing named route `/`; `/home/` becomes the shared landing. Keep the root setup route to preserve existing deep links. New home links always use `app-home`.
- Retain `RoleLandingPage` rows for history, stop using them for `/home/`, and label configuration deprecated. Remove `post_migrate` rewriting of landing settings. Do not delete historical configuration or create a home redirect loop.
- Server-rendered sidebar, header for brand/user/logout/health, visible current route, skip link, viewport metadata, remembered desktop collapse state, and accessible mobile drawer with Escape/focus return. No new frontend framework needed.
- WP1 shows honest gates for maintenance and mixed receipts until those packages are usable; it is not the complete release.

## File-by-file implementation plan

Paths below are proposed targets; migration filenames are assigned against the actual migration graph during implementation. New files are marked “new.” Tests precede behavior changes.

### WP0 — Baseline prerequisite

| File | Change |
| --- | --- |
| `ledgeros/migrations/0009_alter_ledgerosconnectionsettings_options.py` (new) | Capture existing display-name metadata only; no accounting data migration. |

WP0 completed October 21, 2026. Added the generated `AlterModelOptions` migration for the existing singular/plural connection-settings labels. Docker `sqlmigrate ledgeros 0009` confirms the operation is a SQL no-op. `make check` passes: no Django system issues and no missing migrations. Docker `python manage.py test ledgeros.tests.test_management_commands --noinput` passes all five tests after applying migrations to a disposable test database. The normal application database was not migrated during this work. No accounting behavior changed.

### WP1 — Home and navigation (HOME-01–08)

Implemented October 21, 2026: shared authenticated home, responsive sidebar across existing screens, role-aware read/create links, real bounded local receipt/payment-confirmation queues, separate readiness/health messages, and clear gates for later workflows. Home GET is read-only even without singleton setup rows. Reporting-page unsafe methods now require bookkeeping roles, unassigned/inactive accounts fail workflow role checks, and read-only pages hide write actions. Lists without bulk actions no longer show inert bulk controls. Historical landing settings remain intact and read-only; migration bootstrap no longer rewrites them.

Validation: `docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test --noinput` passed 126 tests in 539.934 seconds. After adding three scenarios for ready setup, read-only detail actions and legacy landing bootstrap, `docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test ledgeros.tests.test_workflow_home ledgeros.tests.test_health --noinput` passed all 20 focused tests in 10.550 seconds. Both runs destroyed their test databases normally. `make check` passed with no system issues or missing migrations. Docker `findstatic ledgeros/workflows.css ledgeros/navigation.js` and Node `--check` on both JavaScript files passed. Local read-only inventory found zero active non-superusers without recognized workflow roles. [Browser acceptance and screenshots](qa/wp1/README.md) cover desktop/mobile, persisted collapse, focus containment/return, existing record navigation, viewer and outage states using fictional data in a separate disposable database.

WP1 did not implement bill approvals/grants, actor-aware financial service changes, maintenance requests, mixed receipt posting, or complete outage enforcement across existing posting endpoints. WP2 now supplies the bill approval and payment authorization controls. Maintenance, mixed receipts, and broader integration/release work remain WP3–WP6. Existing record URLs and accounting behavior otherwise remain intact. No production deployment or live LedgerOS financial acceptance was performed.

| File | Change |
| --- | --- |
| `ledgeros/tests/test_workflow_home.py` (new) | All roles, anonymous/unassigned access, genuine scoped queues, setup/outage states, no local writes or external POSTs on home GET. |
| `ledgeros/tests/test_roles_and_audit.py` | Replace redirect expectations, cover custom legacy landing configs and explicit role requirements. |
| `propertyledger/views.py` | Replace redirect view with authenticated shared home backed by read-only context. |
| `propertyledger/urls.py` | Keep `/home/` name and login behavior; wire the home view. |
| `ledgeros/navigation.py` | Shared home destination; centralized navigation items filtered by the same capabilities used by routes. |
| `ledgeros/signals.py` | Stop overwriting deprecated role landing configuration on migration; keep role bootstrap. |
| `ledgeros/admin.py` | Explain/deprecate role landing configuration without deleting rows. |
| `ledgeros/roles.py`, `ledgeros/permissions.py` | Explicit access decisions, deny unassigned workflow writes, distinguish read access from mutation access. |
| `propertyledger/workflows.py` (new) | Read-only home readiness/health/queue composition; integrate later package queues without placeholder metrics. |
| `ledgeros/services.py` | Let the home health probe use already-read connection configuration without singleton creation; preserve existing setup callers. |
| `ledgeros/templates/ledgeros/workflow_home.html` (new) | Three recognizable workflow cards, real links, gated future actions, queues, empty/error states. |
| `ledgeros/templates/ledgeros/base.html` | Sidebar/header layout across existing pages; small readiness display; preserve POST logout. |
| `ledgeros/static/ledgeros/workflows.css`, `ledgeros/static/ledgeros/navigation.js` (new) | Responsive styles and accessible collapse/drawer behavior. |
| Existing test fixtures using unassigned users | Assign intended explicit roles; retain real negative tests for unassigned users. |

### WP2 — Approval, authority and payment enforcement (AP-01–07, OPS-04)

Implemented October 21, 2026: additive workflow authorization and bill-approval models; draft, submit, independent approve/reject/withdraw, and explicit post actions; current-database grant checks; service-, UI-, admin-, and command-level actor enforcement; prospective approval of legacy posted bills without journal changes; and payment retry preservation after grant revocation. New bills no longer auto-post on save. New vendor settlements start from an approved bill and retain the existing signed submission UUID, fingerprint, row lock, balance validation, and LedgerOS idempotency behavior. Debt-service payments and credit-card payoffs remain separate workflows.

Migration `payments.0006_workflow_authorization_and_bill_approval` marks existing posted bills `Legacy / approval not recorded`, leaves existing drafts as drafts, creates no user grants, and does not modify sync records or LedgerOS journals. An administrator must configure explicit grants after deployment. Existing posted bills can then be submitted and approved prospectively before a new settlement; historical payments remain unchanged.

Validation: `make check` passed with no system or migration issues. The full Docker test suite passed all 142 tests. The focused WP2 suite covers independent grants, self-approval denial, stale/submitted edits, concurrent decisions, rejection and resubmission, legacy prospective approval, direct UI/admin/service bypasses, signed bill-scoped payment entry, revocation, and retry identity. No application database migration, production operation, or live LedgerOS financial acceptance was performed.

| File | Change |
| --- | --- |
| `payments/tests/test_bill_approval.py`, `payments/tests/test_workflow_authorization.py` (new) | Self-approval, stale edits, independent grants/revocation, concurrent decisions, legacy approval, service/UI/admin bypass tests. |
| `payments/tests/test_bill_payment_flow.py`, `payments/tests/test_bill_payment_status.py`, `payments/tests/test_payments_workflow.py` | Preserve duplicate/timeout/card safety; require real approvals/grants for new settlement; direct denied POSTs. |
| `payments/models.py` | User grants, independent bill approval data/history, actor attribution and approved financial fingerprint. |
| `payments/migrations/` (new migration) | Additive schema; explicit legacy labels; no fictional approval/grants and no journal rewrite. |
| `payments/authorization.py` (new) | Current user capability predicates and enforcement shared by templates/views/services. |
| `payments/approval_services.py` (new) | Grant administration; save/submit/withdraw/approve/reject/reapprove with locking, audit and actor checks. |
| `payments/services.py` | Add required actor/provenance to affected bill/payment entry points; validate approval/version/grants for new settlement; preserve original retry/reconciliation identity. |
| `payments/forms.py` | Explicit draft/submit actions and immutable system fields; pass actor for validation without trusting client role/status. |
| `payments/views.py`, `payments/urls.py` | Approval queue/actions, authorization administration, per-user payment routes and bill sync guards. |
| `payments/admin.py` | Service-backed authorized writes/actions, grant administration, read-only approval/posting metadata. |
| `payments/management/commands/reconcile_bill_card_payments.py` | Preserve read-only preview; explicit authorized actor and audited apply path that links only verified existing journals. |
| `payments/templates/payments/vendor_bill_list.html`, `vendor_bill_detail.html`, `vendor_payment_detail.html`, `bill_payment_form.html` | Separate approval/posting/balance badges, correct next action and retry/legacy explanations. |
| Approval queue and authorization templates (new under `payments/templates/payments/`) | Real review/grant workflows, CSRF protected POSTs, clear deny/revoke states. |
| `ledgeros/management/commands/seed_beta_demo_data.py` | Seed realistic independent submitter/approver/payer demo scenarios using services. |
| `ledgeros/roles.py`, `ledgeros/admin.py` | Keep generic Django permission editing from conferring new economic grants or changing protected workflow state. |

### WP3 — Maintenance lifecycle (MAINT-01–03, 07–08)

Implemented October 21, 2026: additive maintenance request and immutable event models; required and optional context validation; explicit open, triage, assignment, progress, hold/resume, verification, closure, cancellation, and reasoned reopening transitions; actor attribution, row locks, optimistic versions, admin protections, role-aware request pages, shared navigation, and a real active-maintenance home queue. Maintenance remains local during LedgerOS outages and has no accounting side effects. Closure records invoice pending versus no external cost independently of vendor payment.

Migration `payments.0007_maintenance_request_workflow` creates no requests and changes no bills, payments, sync records, or journals. Photo upload controls remain absent because this deployment has no configured private durable storage or image decoder.

Validation: `make check` passed with no system or migration issues. The focused maintenance and shared-home suite passed all 25 tests. The full Docker suite passed all 153 tests in 43.308 seconds and destroyed its test database normally. No LedgerOS mutation or live financial acceptance was required because WP3 is a local operational workflow.

| File | Change |
| --- | --- |
| `payments/tests/test_maintenance_workflow.py` (new) | Required/scope fields, role matrix, transitions/concurrency, verified closure, no-cost closure, reasoned reopening and outage-safe writes. |
| `payments/models.py`, `payments/migrations/` (new migration) | Request model, immutable transition history, indexes, nullable origin metadata, conditional private attachments. |
| `payments/maintenance_services.py`, `maintenance_forms.py`, `maintenance_views.py` (new) | Authorized local lifecycle services and UI, safe context validation and audited transitions. |
| `payments/urls.py` | Request list/create/detail/edit/transition routes, preserving category routes. |
| `payments/templates/payments/maintenance_list.html`, `maintenance_form.html`, `maintenance_detail.html` (new) | Queue, creation, progress, verification/closure/reopening; separate financial summary. |
| `payments/admin.py` | Requests/history with service-backed mutations; no editable lifecycle bypass. |
| `ledgeros/roles.py`, `payments/authorization.py` | Explicit maintenance authority matrix. |
| Attachment support | Deferred: configure durable private storage, content validation, protected downloads and a decoder dependency before exposing photos. |

### WP4 — Request-to-AP handoff (MAINT-04–06)

Implemented October 21, 2026: a nullable protected request link on vendor bills, one-request/many-bill relationships, actor-attributed link/unlink history, property/unit validation, manager link authority, bill-editor-only creation, safe request prefill, signed UUID replay protection, reciprocal detail links, batched payable states, and a real verified/closed work-awaiting-invoice queue. Bill handoff works at any request state and never changes maintenance closure, approval, posting, payment, sync records, or journals.

Migration `payments.0008_maintenance_bill_handoff` adds nullable link and submission UUID fields and extends maintenance event choices. It creates no bills, invents no links, and changes no accounting data. `make check` passed with no system or migration issues. Focused WP3/WP4 validation passed all 20 tests, and the final full Docker suite passed all 162 tests in 46.052 seconds before destroying its test database normally.

| File | Change |
| --- | --- |
| `payments/tests/test_maintenance_billing.py` (new) | Multiple vendors/bills, partial payments, pre/post closure linking, property/unit mismatch, duplicate saves, credit/reversal independence. |
| `payments/models.py`, `payments/migrations/` (new migration) | Nullable protected request link on bill and unique handoff submission identity. |
| `payments/maintenance_services.py`, `maintenance_forms.py`, `maintenance_views.py` | Create/link existing bill actions, safe prefill, duplicate prevention, linkage audit and batched financial summaries. |
| `payments/services.py`, `payments/approval_services.py`, `payments/forms.py`, `payments/views.py` | Integrate bill creation with existing approval/posting service and request context; no posting on form GET. |
| `payments/urls.py`, maintenance detail and vendor bill detail templates | Reciprocal links and independent operational/approval/posting/payable statuses. |
| `propertyledger/workflows.py` | Enable real maintenance/AP queues and CTAs after routes are functional. |

### WP5 — Mixed receipts, gated on contract proof (RENT-01–07)

| File | Change |
| --- | --- |
| `payments/tests/test_mixed_receipts.py` (new) | Rent-only/deposit-only/mixed allocations, exact journal effects, partial success, immutable retries, double submission/concurrency and finalization. |
| `payments/models.py`, `payments/migrations/` (new migration) | Receipt-owned deposit allocation and persisted frozen component identities/payloads; preserve existing invoice allocation rows/keys. |
| `payments/services.py` | Explicit deposit journal builder/posted confirmation, component orchestration and complete local summary; no parent financial posting. |
| `payments/forms.py`, `payments/views.py`, `payments/urls.py` | Reviewed rent/deposit split and safe retry/reconciliation UX, no post-finalization economic edits. |
| `payments/admin.py` | Protect component/state fields and route actions through the same services. |
| `payments/templates/payments/payment_form.html`, `payment_detail.html`, deposit detail/list templates | One receipt with clear components and per-component references/failure states. |
| `reports/services.py`, `reports/tests/test_reports_workflow.py` | Rent/deposit separation across tenant ledger, owner statements and property totals; partial posted visibility and tested legacy fallback. |
| `propertyledger/workflows.py` | Enable combined receipt CTA only after proof and integration tests. |
| Sibling LedgerOS API/service/tests (conditional, separately scoped) | Only the smallest extension demonstrated necessary by contract proof; no upstream edits made by this plan. |

### WP6 — Integration, documentation and release (OPS-01–04 and all acceptance scenarios)

| File | Change |
| --- | --- |
| `payments/tests/test_workflow_outages.py` (new), home/approval/maintenance/receipt tests | Realistic unavailable/permission/setup distinctions; service outage and recovery; denial of unsafe finalization/payment. |
| `ledgeros/services.py`, `propertyledger/workflows.py`, affected mutation services/views | Shared bounded readiness checks and degraded behavior; upstream validation remains authoritative. |
| Existing shared/page templates | Keyboard/mobile consistency, usable forms/tables, no fake metrics/dead links; production static-file delivery verified. |
| `docs/technical-manual.md`, `docs/user-manual.md` | Current states, grants, journals/retries, maintenance handoff, mixed report semantics and historical reconciliation rules. |
| `docs/admin-setup.md`, `docs/quick-start.md`, `docs/beta-testing.md` | Grant setup, private attachment prerequisites, non-destructive migration/acceptance path and role scenarios. |
| `README.md`, this plan | Accurate status/index, actual verification evidence and remaining scope. Archives remain historical. |

## Dependencies and risks

| Work | Depends on | Material risk | Gate / mitigation |
| --- | --- | --- | --- |
| WP0 | Current migration graph | Existing migration check already fails | Metadata-only migration before behavior changes; rerun dry-run. |
| WP1 | Explicit route/capability map | Unassigned-user compatibility; legacy redirects; read-only GET creating setup rows | Inventory current roles; update only explicit access rules; test fresh empty DB GET and custom landing config. |
| WP2 | Actor-aware services and audited grants | Alternate payment/admin/command path bypasses; uncertain prior attempts; races | Inventory all callers; required actor at service boundary; row locks, immutable payloads; no replacement payments. |
| WP3 | Local role matrix; attachment deployment if enabled | Invalid scope, stale transitions, unsafe/public uploads | Service validation/version checks; private storage proof before upload UI. |
| WP4 | WP2 + WP3 | Duplicate bill, posted bill reattribution, payment/closure coupling | Unique submission identity, explicit audited links and independent state tests. |
| WP5 | LedgerOS proof; deposit history inventory | Audit-only deposits, double cash, wrong cash account/date, timeout replay, reports treating deposits as rent | Financial gate; exact journals/account balances/IDs; no automatic historical correction; report contract tests. |
| WP6 | All released packages | UI suggests finished workflows; outage numbers look authoritative; old binary bypasses new gates | Enable only completed paths; unavailable labels; coordinated deploy; keep payment writes disabled during rollback. |

Recommended sequence: WP0 → WP1 → WP2 → WP3 → WP4 → WP5 → WP6. Perform read-only LedgerOS receipt contract research early; WP1–WP4 do not depend on mixed posting proof. This sequence does not authorize deployment or production mutations.

## Verification and release criteria

For each behavioral slice, add failing invariant tests first, implement, then run relevant tests in Docker. Test authorization at UI POST, service and admin boundaries; include concurrent submissions and timeout recovery. For home GET, assert no database writes and no upstream mutation requests on a fresh unbootstrapped database as well as a ready one.

Required final checks:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py check
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py makemigrations --check --dry-run
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test --noinput
make check
```

Verify migrations first against disposable databases, including an upgrade fixture with legacy posted/failed/attempted transactions. Do not use reset scripts against real bookkeeping data. Run migrations and real API acceptance only in a prepared non-production sandbox, preserving evidence of deployment versions/scopes/account mappings.

Acceptance evidence must cover PRD §12 scenarios 1–14: shared role home; mobile/sidebar; rent-only/mixed and interrupted receipts; independent bill approval/payment; partial settlement; multi-vendor maintenance; invoices before/after closure; reopening/no-cost closure; outage recovery; reports/history regressions. Capture desktop/mobile screenshots and keyboard/focus results. For maintenance-only actions, assert no accounting mutation. For bill settlement, assert no changes to accrued bill expense, owner expense totals or tenant ledgers. For mixed receipts, assert Cash 2,000 / AR 1,500 / deposit liability 500 with no replay changes.

Rollout uses additive migrations and explicit authorization setup before enabling payment writes. Keep historical sync/audit IDs intact. Rollback must first disable affected financial writes; deploying an old binary that ignores approvals is unsafe. Preserve new rows/columns and use a forward fix or read-only fallback rather than deleting posted evidence. Export a read-only compatibility inventory of legacy bills, attempted payments, deposit audit events and parent-only receipts before the financial release.

## Discovery verification results

- `docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py check`: passed, no issues.
- `docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py makemigrations --check --dry-run`: failed, exit 1; proposes metadata migration `ledgeros.0009_alter_ledgerosconnectionsettings_options`. No migration was generated or applied.
- `docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test --noinput`: passed, 115 tests in 510.398 seconds; exit 0. Test database was destroyed normally. Logged sync failures were exercised failure scenarios, not test failures.
- `git diff --check`: passed for tracked documentation changes.
- No live LedgerOS accounting acceptance, migration application, production operation, or screenshot QA was performed during this planning task.
