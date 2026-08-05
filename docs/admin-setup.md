# Admin Setup Guide

This guide is for the admin who prepares PropertyLedger before any feature testing, beta sessions, or day-to-day use.

The short version:

1. start PropertyLedger and LedgerOS
2. make sure LedgerOS has an open accounting period
3. save the LedgerOS connection settings in PropertyLedger
4. copy the selected LedgerOS entity and accounting period into PropertyLedger
5. configure the required account mappings
6. run the setup smoke check

If those steps are not complete, feature testing will mostly measure setup gaps instead of the product itself.

## What this screen does

The `PropertyLedger Setup` screen has two different jobs:

- `LedgerOS Connection` stores how PropertyLedger reaches LedgerOS.
- `Selected LedgerOS Books` stores which LedgerOS entity and accounting period PropertyLedger is using.

That separation is intentional.

- Connection settings are technical plumbing.
- Selected books are the accounting context.
- Account mappings tell PropertyLedger how to translate property workflows into LedgerOS accounts.

## Before you start

Make sure you have:

- the PropertyLedger repo;
- the sibling LedgerOS v2 repo;
- Docker and Docker Compose;
- a running LedgerOS web stack;
- a running PropertyLedger web stack.

For local beta-style setup, use the provided scripts:

```bash
bash scripts/beta-reset.sh
bash scripts/beta-seed.sh
make up
cd ../ledgeros_v2 && WEB_PORT=8001 make up
```

## Step 1: Confirm LedgerOS is available

Open LedgerOS directly:

- Admin: `http://localhost:8001/admin/`
- API root: `http://localhost:8001/api/v1/`

If you need to log in there, create a LedgerOS admin user first:

```bash
cd ../ledgeros_v2
docker compose run --rm web python manage.py createsuperuser
```

In LedgerOS admin, confirm:

- the default entity exists;
- there is an open accounting period;
- the sample chart of accounts is loaded.

## Step 2: Open PropertyLedger setup

Open the PropertyLedger setup screen:

- `http://localhost:8000/`

You should see:

- local health;
- setup checklist;
- recommended order;
- LedgerOS health;
- selected LedgerOS books;
- LedgerOS connection;
- AP mapping;
- account mappings.

## Step 3: Save the LedgerOS connection settings

In the `LedgerOS Connection` section, enter the connection values that tell PropertyLedger how to reach LedgerOS:

- `Base URL`
- `Host header` if needed
- `Client ID`
- `HMAC secret env var`
- `API key env var` if your LedgerOS deployment requires it
- `Health path`
- `Timeout seconds`

Use these rules:

- `Base URL` should point to the reachable LedgerOS web URL.
- `Client ID` must match the client configured in LedgerOS.
- `HMAC secret env var` should usually remain `LEDGEROS_HMAC_SECRET`.
- Leave `Host header` blank unless LedgerOS needs a specific host name.
- Leave `API key env var` blank unless the deployment explicitly requires bearer auth.

Save the form, then confirm the connection settings were stored.

## Step 4: Copy the selected LedgerOS books

The `Selected LedgerOS Books` section should show:

- `LedgerOS entity id`
- `LedgerOS entity name`
- `LedgerOS accounting period id`
- `LedgerOS accounting period name`

If those fields are blank, the setup is not complete.

Use the values from LedgerOS admin or the beta bootstrap flow and make sure they are copied into PropertyLedger.

For the beta demo, the seed script should already populate these values.

## Step 5: Configure account mappings

PropertyLedger needs account mappings before setup can complete.

Required mappings:

- `operating_bank_account`
- `undeposited_funds`
- `accounts_receivable`
- `accounts_payable`
- `rental_income`
- `repairs_and_maintenance_expense`
- `tenant_security_deposits_liability`
- `owner_contributions_equity`
- `owner_distributions_equity`

Optional mappings that should be enabled only if you need them:

- `credit_card_liability`
- `mortgage_or_loan_liability`
- `interest_expense`
- `principal_payment_mapping`

The `Accounts Payable Mapping` section is the quickest one to fill manually because the setup page exposes it directly.

For the other mappings, use the account mapping rows on the page and verify that each one has:

- an account code
- an account name
- an account type
- enabled state appropriate to the mapping

## Step 6: Run the health and smoke checks

After connection settings and mappings are in place, verify:

1. local health is healthy;
2. LedgerOS health is healthy;
3. the selected entity and accounting period are populated;
4. required account mappings are present and valid;
5. the setup smoke check passes.

Run the smoke check with either:

```bash
make smoke
```

or the `Run setup smoke` button on the setup page.

Both paths now record the smoke result back onto the setup screen.

If setup is not complete, use the `Recommended Order` section to find the next missing step.

## Beta demo example

When you are preparing the beta demo, use these seeded records:

- owner: `Cedar Grove Holdings LLC`
- property: `Cedar Grove Apartments`
- units: `101`, `102`, `103`
- tenants: `Avery Jordan`, `Brooke Chen`, `Carlos Rivera`
- vendors: `Ace Plumbing`, `Bright Electric`, `GreenLine Landscaping`
- maintenance categories: `Plumbing`, `Electrical`, `Landscaping`
- demo users: `beta-admin`, `beta-manager`, `beta-bookkeeper`

Representative beta records:

- unit `101` with tenant `Avery Jordan`, rent `1450.00`, deposit `1450.00`
- unit `102` with tenant `Brooke Chen`, rent `1575.00`, deposit `1575.00`
- unit `103` with tenant `Carlos Rivera`, rent `1695.00`, deposit `1695.00`
- draft tenant charge: `Landscape cleanup charge` for `125.00`
- vendor bill: `Ace Plumbing` for `240.00`
- vendor bill: `Bright Electric` for `180.00`
- vendor bill: `GreenLine Landscaping` for `315.00`
- draft vendor payment: `Ace Plumbing` with check number `BETA-1001`
- three draft security deposit events tied to the three leases

Default demo password:

- `PropertyLedgerBeta123!`

## When setup is done

You are ready to start feature testing only after:

- the setup screen shows the selected LedgerOS entity and accounting period;
- the required account mappings are present;
- the LedgerOS health check passes;
- the setup smoke test passes.

At that point, PropertyLedger is ready for property, payments, and reporting workflows.
