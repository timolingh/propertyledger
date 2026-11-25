# Archived admin setup demo

Moved from the Admin Setup Guide on November 24, 2026. This is synthetic test data for disposable environments. See the [beta guide](./beta-testing.md) for demo preparation.

## Historical demo bootstrap

For the beta demo, the seed script should already populate the selected LedgerOS entity and accounting period. It also provisions LedgerOS account `2200` as the active, credit-normal tenant security deposit liability and verifies the corresponding PropertyLedger mapping. If an existing `2200` account has conflicting settings, seeding stops instead of changing its accounting treatment.

If LedgerOS web is not running yet, the seed script will warn and continue instead of failing. Run `make smoke` after both web stacks are up.

## Demo records

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

