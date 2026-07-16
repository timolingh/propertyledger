# Beta Focus Group Session Guide

Use this guide when you are running a one-hour beta session with real users.

The goal is not to “test every feature.” The goal is to watch people try to understand the product, move through the core workflows, and explain where the experience feels clear or confusing.

## Session setup

Start from a clean slate before the group arrives:

```bash
bash scripts/beta-reset.sh
```

Then seed the demo environment:

```bash
bash scripts/beta-seed.sh
```

This prepares both local stacks and seeds a realistic demo property-management setup.

### Seeded demo data

The session should use these specific records:

- owner: `Cedar Grove Holdings LLC`
- property: `Cedar Grove Apartments`
- units: `101`, `102`, `103`
- tenants: `Avery Jordan`, `Brooke Chen`, `Carlos Rivera`
- vendors: `Ace Plumbing`, `Bright Electric`, `GreenLine Landscaping`
- maintenance categories: `Plumbing`, `Electrical`, `Landscaping`
- demo users: `beta-admin`, `beta-manager`, `beta-bookkeeper`

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

Default demo password:

- `PropertyLedgerBeta123!`

## How to run the hour

Ask participants to move through the product in the order below.

1. Start with the admin/setup view.
2. Move into property management.
3. Finish with payments, bills, and reports.
4. End with open-ended feedback.

Tell people up front that they should think out loud. You want them to narrate what they expect to happen before they click.

## Minute 0 to 10: First impression and setup

Give the group the admin user first:

- username: `beta-admin`
- password: `PropertyLedgerBeta123!`

Ask them to open the admin screen:

- `http://localhost:8000/admin/`

Then send them to the setup screen:

- `http://localhost:8000/`

Ask them to do these things in order:

1. Look for the LedgerOS connection and setup status.
2. Confirm the page already shows the LedgerOS entity and accounting period.
3. Find the setup information for `Cedar Grove Apartments`.
4. Say out loud whether the page feels ready to use or still feels half-configured.

What to listen for:

- Do they understand what LedgerOS is doing here?
- Do they know whether they are “set up” yet?
- Do they have to guess where to begin?

## Minute 10 to 25: Property management flow

Switch them to the property manager account:

- username: `beta-manager`
- password: `PropertyLedgerBeta123!`

Ask them to move through these pages:

- `http://localhost:8000/properties/`
- `http://localhost:8000/units/`
- `http://localhost:8000/tenants/`
- `http://localhost:8000/leases/`

Ask them to complete these tasks:

1. Find `Cedar Grove Apartments`.
2. Find units `101`, `102`, and `103`.
3. Find tenants `Avery Jordan`, `Brooke Chen`, and `Carlos Rivera`.
4. Open one lease and explain, in plain language, who lives in which unit and what the rent is.
5. Tell you whether the relationships between property, unit, tenant, and lease feel obvious.

Use this as a concrete prompt:

- “Show me who lives in unit `101` and what rent they pay.”

What to listen for:

- Can they navigate by instinct?
- Do they understand the object model without explanation?
- Do they notice when a record belongs to another record?

## Minute 25 to 40: Payments and bills

Switch them to the bookkeeper account:

- username: `beta-bookkeeper`
- password: `PropertyLedgerBeta123!`

Ask them to open the payments area:

- `http://localhost:8000/payments/`

Then give them this sequence:

1. Find the vendor bills.
2. Identify the bill for `Ace Plumbing`.
3. Identify the bill for `Bright Electric`.
4. Identify the bill for `GreenLine Landscaping`.
5. Open the vendor payment for `Ace Plumbing`.
6. Open the security deposit area and look for the three seeded deposit events.

Ask them to describe what seems ready for action and what seems like a draft or in-progress record.

Use concrete prompts like:

- “Which of these bills looks most like something you would actually enter today?”
- “Which fields help you trust that the bill is attached to the right property?”
- “Does the payment screen make it clear what has already been recorded?”

What to listen for:

- Can they tell bills, payments, and deposits apart?
- Do the statuses make sense?
- Do the amounts feel believable?

## Minute 40 to 50: Reports and confidence check

Ask participants to review the reports area and confirm `Cedar Grove Apartments` appears in the reporting pages.

If they need help, direct them to the reporting views already available in the app and ask them to answer these questions:

1. What would you expect to learn from this report?
2. Does the report seem tied to the property they were just exploring?
3. Would they trust this screen enough to make a decision from it?

This is the right time to ask whether the product feels accounting-first, property-first, or something in between.

## Minute 50 to 60: Open feedback

Close the session with a short discussion.

Ask each person:

1. What was the easiest thing to understand?
2. What felt confusing or too hidden?
3. Which screen would you change first?
4. Which one record, label, or amount made the product feel real?
5. What would you expect to do next if this were your actual job?

Capture feedback on:

- whether the seeded examples felt realistic;
- whether the names, amounts, and dates helped them orient quickly;
- whether the setup screen explained the product well enough;
- whether the property, payments, and reports workflows felt connected.

## Moderator notes

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
