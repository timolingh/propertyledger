# Beta Testing Guide

This guide is for human beta testers.

It starts from a clean slate, prepares both local repos, and then walks through role-based manual checks.

## 1. Reset to a clean slate

Run the reset script first if you want to clear local demo data and start over:

```bash
bash scripts/beta-reset.sh
```

This resets both local Docker stacks:

- `propertyledger`
- `ledgeros_v2`

Use this when:

- you want to start fresh;
- you previously ran a beta seed and want to wipe the demo data;
- you want to reproduce the initial beta experience from scratch.

## 2. Prepare the system

After resetting, run the beta seed:

```bash
bash scripts/beta-seed.sh
```

It seeds the sibling `ledgeros_v2` repo first, then seeds PropertyLedger with the demo setup data, property, units, tenants, vendors, starter charges, starter bills, and demo users needed for manual testing.

What the preparation step does:

- starts both local stacks;
- imports the sample LedgerOS chart of accounts;
- creates or reuses an open accounting period;
- bootstraps PropertyLedger connection settings;
- bootstraps required account mappings;
- seeds the demo property and role users.

## 3. Demo accounts

After seeding, use these demo users:

- `beta-admin`
- `beta-manager`
- `beta-bookkeeper`

Use the password you passed to the seed command, or the default if you did not supply one.

## 4. Admin checklist

1. Sign in as `beta-admin`.
2. Open the admin screen.
3. Confirm the connection settings, account mappings, and setup rows are present.
4. Open the setup screen and verify the demo property and setup state are visible.
5. Confirm the demo property is named `Cedar Grove Apartments`.
6. Confirm the vendor and tenant records are present.

## 5. Property manager checklist

1. Sign in as `beta-manager`.
2. Open the properties, units, tenants, and leases screens.
3. Confirm the demo property and three units are visible.
4. Confirm the three demo tenants are visible.
5. Open a lease and check that the property, unit, and tenant relationships make sense.
6. Verify you can review the operational records without touching system configuration.

## 6. Bookkeeper checklist

1. Sign in as `beta-bookkeeper`.
2. Open the payments area.
3. Confirm the vendor list, vendor bills, tenant payments, and security deposit views are available.
4. Open the seeded vendor bills and confirm the amounts and vendor names look realistic.
5. Review the reports area and confirm the seeded property appears in reporting pages.
6. If you are testing record entry, create a small additional charge or payment and confirm it follows the normal workflow.

## 7. Suggested order

1. Seed the beta data.
2. Review the admin checklist.
3. Review the property manager checklist.
4. Review the bookkeeper checklist.
5. Capture notes on what felt confusing, slow, or missing.

## 8. Notes for feedback

- Did the demo data feel realistic?
- Were the role permissions obvious?
- Was the setup screen understandable?
- Did any terminology feel inconsistent with real property management work?
