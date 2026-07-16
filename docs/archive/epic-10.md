# Epic 10 Decision Record

Epic 10 in this repo covers API documentation and agent-built connector support.

## Purpose

Make the system usable by sophisticated users and AI agents building connectors.

## Public API boundary

The current public programmatic API surface is intentionally small:

- `GET /api/health/local/`
- `GET /api/health/ledgeros/`
- `POST /api/v1/sync-events/`

UI routes under `/`, `/owners/`, `/properties/`, `/charges/`, and `/payments/` are application pages, not stable public API surfaces.

Any future `/api/v1/*` route intended for external clients should be added to this list before the docs treat it as stable.

## In scope

- external API documentation for the public `/api` surface;
- LedgerOS adapter documentation;
- example client prompts;
- example payloads;
- sync error handling guide;
- test sandbox instructions;
- OpenAPI schema if practical;
- API versioning guidance.

## Out of scope

- QuickBooks/Xero connectors;
- payment processor connectors;
- bank-feed connectors;
- tenant portal API;
- owner portal API.

## Required documentation topics

- authentication model;
- idempotency behavior;
- external ID rules;
- retry behavior;
- duplicate handling;
- request/response logging and secret redaction;
- local object IDs versus LedgerOS resource IDs;
- sandbox/LedgerOS startup path;
- examples for tenant charge, tenant payment, vendor bill, and manually recorded management-fee expense.

## File targets

Use these files as the working set for Epic 10 documentation:

- `docs/epic-10.md` - Epic 10 decision record and working outline.
- `docs/propertyledger-implementation-epics.md` - master epic index and traceability anchor.
- `README.md` - repo-level entry point for developer-facing docs.
- `docs/api.md` - external API reference for the current public `/api` surface.
- `docs/connector-guide.md` - connector and agent guide for external clients.
- `docs/openapi.md` or generated OpenAPI artifacts - only if we decide OpenAPI is practical.

If we keep the documentation in fewer files, `docs/api.md` can absorb the canonical API reference and the connector guide can stay as a section in the same file.

## Writing plan

### Phase 1: Define the public surface

- Confirm the exact `/api` endpoints that are public.
- Mark everything else as UI-only or internal.
- Add a short note explaining that public API scope is intentionally narrow.

### Phase 2: Document the contract

- Describe authentication.
- Describe idempotency and duplicate handling.
- Describe request and response logging rules.
- Explain local object IDs versus LedgerOS resource IDs.
- Explain retry behavior and when a client must stop retrying.

### Phase 3: Add examples

- Add a tenant charge example.
- Add a tenant payment example.
- Add a vendor bill example.
- Add a manual management-fee expense example.
- Add one generic sync-event example that shows the full envelope.

### Phase 4: Add connector guidance

- Explain how an agent or integration should build around the adapter boundary.
- State what should never be bypassed.
- Provide a small “do this, not that” list for external clients.

### Phase 5: Add sandbox instructions

- Show how to start the app locally.
- Show how to point it at a running LedgerOS endpoint.
- Show which environment variables matter.
- Show which smoke checks to run before testing a client.

### Phase 6: Decide on OpenAPI

- Publish generated schema if it stays aligned with the code.
- Otherwise document why it is deferred and keep the hand-written reference authoritative.

## Document sections

### 1. API overview

- What PropertyLedger is.
- What parts of the product are public API versus UI only.
- How the adapter boundary keeps accounting mutations behind LedgerOS.

### 2. Authentication model

- Document the current auth state for each public endpoint.
- State whether a route is read-only, trusted-client only, or user-authenticated.
- Call out any additional auth required before an endpoint should be treated as external-facing.

### 3. Endpoint inventory

- `GET /api/health/local/`
- `GET /api/health/ledgeros/`
- `POST /api/v1/sync-events/`

For each endpoint, document:

- purpose;
- request shape;
- response shape;
- error conditions;
- retry expectations;
- whether the endpoint changes accounting state.

### 4. Idempotency and duplicates

- `Idempotency-Key` is required for sync-event writes.
- Replays with the same key and identical request body return the same logical result.
- Replays with the same key but different payload are rejected.
- External IDs should stay stable for a logical event.

### 5. Object identity rules

- Local object IDs belong to PropertyLedger.
- LedgerOS resource IDs belong to LedgerOS.
- Connector docs must show both when relevant and explain which one the client owns.

### 6. Error handling

- Validation errors.
- Duplicate detection.
- Missing idempotency key.
- Connector retry guidance.
- When to stop retrying and surface a manual reconciliation step.

### 7. Example payloads

Use the sync-event envelope as the connector-facing example format:

```json
{
  "source_system": "propertyledger",
  "domain_event_type": "tenant_charge.created",
  "external_id": "tenant_charge:123",
  "source_object_type": "tenant_charge",
  "source_object_id": "123",
  "occurred_at": "2026-07-16T12:00:00Z",
  "payload": {
    "property_id": 10,
    "lease_id": 42,
    "tenant_id": 7,
    "charge_type": "base_rent",
    "amount": "1250.00",
    "description": "July rent"
  }
}
```

Add matching examples for:

- tenant payment;
- vendor bill;
- manually recorded management-fee expense.

### 8. Sandbox instructions

- How to start PropertyLedger locally.
- How to point it at a running LedgerOS endpoint.
- What values come from environment variables.
- How to run the documented smoke checks.

### 9. OpenAPI guidance

- Publish an OpenAPI schema if it is practical to keep it aligned.
- If not, explain why it is deferred and which endpoints are still fully documented by hand.

### 10. Agent guidance

- Do not bypass the accounting adapter boundary.
- Do not treat UI pages as stable external API.
- Do not assume an internal endpoint is public unless the docs list it explicitly.

## Acceptance criteria

- A technical user can build a client using docs alone.
- Example payloads exist for tenant charge, tenant payment, vendor bill, and manual management-fee expense.
- Docs explain idempotency, duplicate handling, retries, and external IDs.
- Agent guidance states not to bypass accounting adapter boundaries.
- OpenAPI schema exists or the doc explains why it is deferred.
- The doc set names the canonical file or files that external users should read first.

## Docker/manual checks

- Run tests inside Docker.
- Validate example payloads against serializers/schemas where practical.
- Confirm docs match actual endpoints.
