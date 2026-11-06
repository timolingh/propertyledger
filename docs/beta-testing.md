# Beta Focus Group Session Guide

Use this guide when you are running a one-hour beta session with real users.

The goal is not to “test every feature.” The goal is to watch people try to understand the product, move through the core workflows, and explain where the experience feels clear or confusing.

Admin setup is a prerequisite for beta testing. Complete the setup path first, then bring participants into the product.

If you need the setup checklist, use [Admin Setup Guide](./admin-setup.md).

## Session setup

Start from a clean slate before the group arrives:

```bash
bash scripts/beta-reset.sh
```

Then seed the demo environment:

```bash
bash scripts/beta-seed.sh
```

These scripts reset and seed the demo data, but they do not leave the web apps running.
The seed step also copies the selected LedgerOS entity and accounting period into PropertyLedger so the setup screen is already populated for the session.
It provisions LedgerOS account `2200` as the active, credit-normal tenant security deposit liability and verifies that PropertyLedger's required deposit mapping uses that account.
If LedgerOS web is not running yet, the seed script will warn and continue instead of failing, then you can run `make smoke` after both web stacks are up.

Start the two stacks separately:

```bash
make up
cd ../ledgeros_v2 && WEB_PORT=8001 make up
```

Open these URLs before the session starts:

- PropertyLedger: `http://localhost:8000/`
- LedgerOS v2: `http://localhost:8001/`

If you need to inspect LedgerOS directly during setup, create or confirm a LedgerOS admin user first:

```bash
cd ../ledgeros_v2
docker compose run --rm web python manage.py createsuperuser
```

Then inspect LedgerOS with:

- Admin: `http://localhost:8001/admin/`
- API root: `http://localhost:8001/api/v1/`

This prepares both local stacks and seeds a realistic demo property-management setup.
If the smoke check did not complete during seeding, run `make smoke` after both stacks are up so the setup screen records the result.

### Prepared records for later exercises

Keep these seeded records for later maintenance, approval, partial-payment, and recovery exercises. Start the first walkthrough with the new tenant **Dana Morgan**, created by the tester using the [Guided Workflow Test](./workflow-testing.md#start-here-a-new-tenants-first-payment). The seeded owner and property provide context; do not begin by posting Avery’s prepared receipt.

Prepared records:

- owner: `Cedar Grove Holdings LLC`
- property: `Cedar Grove Apartments`
- units: `101`, `102`, `103`
- tenants: `Avery Jordan`, `Brooke Chen`, `Carlos Rivera`
- vendors: `Ace Plumbing`, `Bright Electric`, `GreenLine Landscaping`
- maintenance categories: `Plumbing`, `Electrical`, `Landscaping`
- demo users: `beta-admin`, `beta-manager`, `beta-bookkeeper`
- review users: `beta-owner-viewer`, `beta-read-only`

The seed assigns independent workflow capabilities for the demo: `beta-manager` can approve vendor bills, `beta-bookkeeper` can record approved vendor payments, and `beta-admin` receives both grants for administrative testing. The Ace Plumbing bill is approved, the Bright Electric bill awaits approval, and the GreenLine Landscaping bill remains a draft.

Seeded vendors are local records and are not automatically synced to LedgerOS. Before posting a vendor's bill, sign in as `beta-bookkeeper` or `beta-admin`, open **Vendors**, choose **Edit** for that vendor, and choose **Save vendor** without changing any fields. Continue only after the message **Vendor saved and provisioned in LedgerOS.** If provisioning fails or remains pending, resolve the reported setup/connectivity issue and save the same vendor again. Repeat for each vendor whose bills you will post; a healthy setup smoke check and local bill approval do not replace vendor provisioning. See [Bill approval, posting, and payment](./workflow-testing.md#4-bill-approval-posting-and-payment) for the full sequence.

Representative records participants should encounter:

- unit `101` with tenant `Avery Jordan`, rent `1450.00`, deposit `1450.00`
- unit `102` with tenant `Brooke Chen`, rent `1575.00`, deposit `1575.00`
- unit `103` with tenant `Carlos Rivera`, rent `1695.00`, deposit `1695.00`
- a draft tenant charge called `Landscape cleanup charge` for `125.00`
- vendor bills for:
  - `Ace Plumbing` for `240.00`
  - `Bright Electric` for `180.00`
  - `GreenLine Landscaping` for `315.00`
- a draft vendor payment for `Ace Plumbing` with check number `BETA-1001`
- three draft security deposit events tied to the three leases
- Avery Jordan’s draft $1,950.00 receipt for unit 101: $1,450.00 rent and a $500.00 security deposit
- maintenance requests: “Kitchen sink is leaking into the cabinet.” (unit 101, Open), “Hallway light flickers intermittently.” (unit 102, On hold), and “Remove fallen branches and restore the rear walkway.” (unit 103, Closed with vendor invoice pending)

Default demo password:

- `PropertyLedgerBeta123!`

For the complete step-by-step acceptance sequence and expected accounting results, use the [Guided Workflow Test](./workflow-testing.md).

## How to run the hour

Use [sections 1–6 of the Guided Workflow Test](./workflow-testing.md#start-here-a-new-tenants-first-payment) as the first story. Ask the tester to think aloud before each action. Let them create the records instead of presenting partially completed ones.

### Minutes 0–5: Confirm setup

As `beta-admin`, confirm the LedgerOS connection, selected open period, mappings, and smoke result. Explain that the seeded owner/property are ready, but the new tenant’s workflow has not started. Agree on the demo dates before handing over.

### Minutes 5–15: Create and provision a tenant

As `beta-manager`, have the tester create **Dana Morgan**, review the tenant, and confirm the **Synced** badge after creation. If the result is not confirmed, follow **Review & sync** and the provisioning review. Confirm success before proceeding. Ask what this did and whether any money has been recorded yet; the answer should be no.

### Minutes 15–25: Create the lease and rent invoice

Have the tester create unit **104** and Dana’s active lease with **$1,450 monthly rent** and **$1,450 required deposit**. Review the lease and the initially unpaid deposit requirement. Switch to `beta-bookkeeper`, create the $1,450 rent invoice, and post it. Ask the tester to explain the **$2,900 total owed** and where each obligation appears.

### Minutes 25–40: Receive and record the first payment

Only now introduce the fictional **$2,900 check**, covering rent and deposit in full. Have the tester create a receipt, enter the **$1,450 deposit allocation** themselves, save for review, apply/post rent, and post the receipt’s deposit portion. Confirm every action’s result before continuing. Do not create a separate deposit-received event for the same money.

### Minutes 40–50: Verify the outcome

Have the tester find Dana’s paid rent invoice, posted $2,900 receipt, and deposit summary showing **$1,450 required / $1,450 received / $0 remaining**. Follow the deposit activity link back to the receipt. Ask them to explain which action created each record, when the payment arrived, and whether any amount remains owed.

### Minutes 50–60: Debrief

Ask what was confusing, which labels were unexpected, and whether the screen made each posting action clear. Record the exact step and screen. If the first story is not understandable, use the remaining time to capture that friction rather than switching into another prepared scenario.

## Later sessions: partial states and recovery

Once the first story is understood, use sections 7–13 of the guided test for permission checks, maintenance, vendor bills, the separate Avery partial-deposit scenario, and outages. Explain the starting state of each prepared record before using it. These exercises test resuming work; they are not the introduction to creating it.

## Moderator notes

Start with the new-tenant story above. For later prepared scenarios, start each role at `/home/` after setup. Check the three workflow cards, existing record/report links, desktop collapse and mobile menu. Confirm read-only viewers can review maintenance while owner viewers and unassigned users cannot. Exercise request creation, hold/resume, verified closure with each invoice outcome, and reasoned reopening. Create two vendor bills from one request with different vendors, link an existing bill after closure, and confirm operational, approval, posting, and payment states remain separate. Repeat a bill submission and confirm it reuses the existing bill. Exercise the separate bill submitter, approver, and payer capabilities with the seeded users. Record rent-only, deposit-only and combined receipts and verify their component references and totals.

Stop LedgerOS, reload the workflow home, and confirm the outage warning and **Unavailable** accounting values. Save a maintenance change, receipt draft and bill draft. Confirm finalization, bill posting and vendor payment are blocked without a new sync attempt. Restart LedgerOS and retry the same saved records, confirming their local IDs and idempotency identities remain unchanged. Maintenance photos remain gated pending private durable storage. See [WP1 browser acceptance](qa/wp1/README.md) for desktop/mobile examples.

- Keep the group moving, but do not rush them past confusion.
- If a participant pauses, ask what they expected to happen.
- Do not explain the system too early; let the interface speak first.
- Focus on comprehension, confidence, and workflow clarity, not just task completion.
- If a screen surprises them, treat that as useful feedback rather than a failure.

## Suggested debrief

After the session, compare notes on these questions:

- Did the product make its purpose obvious within the first few minutes?
- Did the seeded data help people understand the workflows?
- Were there any screens that felt like internal tooling instead of a product for real users?
- Did the property manager and bookkeeper flows feel distinct enough?
- Did the session surface terminology that should be simplified?
