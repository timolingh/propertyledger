# PropertyLedger API Reference

This document describes the public programmatic surface for PropertyLedger as currently defined for Epic 10.

## Public surface

The current public `/api` surface is intentionally narrow:

- `GET /api/health/local/`
- `GET /api/health/ledgeros/`
- `POST /api/v1/sync-events/`

UI pages under `/`, `/owners/`, `/properties/`, `/charges/`, and `/payments/` are not treated as stable external API.

Any future `/api/v1/*` route intended for external clients should be added here before it is treated as stable.

## Authentication model

Current status:

- the app does not enforce a dedicated external API authentication layer on these endpoints;
- the health endpoints are read-only;
- the sync-event endpoint is intended for trusted integrations behind network controls or a future auth layer.

Connector authors should treat the current surface as trusted-client only until a formal API auth scheme is added.

## Endpoint reference

### `GET /api/health/local/`

Purpose:

- deterministic local app and database health check.

Response:

- `200 OK` with a JSON body that includes `healthy: true` when the app and database are available.

Common failure cases:

- database unavailable;
- application runtime error.

### `GET /api/health/ledgeros/`

Purpose:

- deterministic health check for the configured LedgerOS endpoint.

Response:

- `200 OK` when the configured LedgerOS health endpoint returns a healthy payload;
- `503 Service Unavailable` when the check fails.

Expected response body:

- `healthy`
- `source`
- `details`

Common failure cases:

- missing configuration;
- connection timeout;
- authentication failure;
- non-2xx response;
- malformed payload.

### `POST /api/v1/sync-events/`

Purpose:

- record a generic LedgerOS-bound sync event envelope.

Required headers:

- `Content-Type: application/json`
- `Idempotency-Key`

Request body fields:

- `source_system`
- `domain_event_type`
- `external_id`
- `source_object_type`
- `source_object_id`
- `occurred_at`
- `payload`

Response:

- `201 Created` when a new sync record is created;
- `200 OK` when the same idempotency key is replayed with the same payload;
- `409 Conflict` when the idempotency key is reused for a different payload;
- `400 Bad Request` when validation fails or the idempotency key is missing.

The response body includes the sync record metadata, including the local record IDs, request hash, status, and timestamps.

## Idempotency rules

- `Idempotency-Key` is required for sync-event writes.
- The same key with the same logical event should return the same logical result.
- The same key with a different payload must be rejected.
- External IDs should be stable for the logical event they represent.

## Identity rules

- Local object IDs belong to PropertyLedger.
- LedgerOS resource IDs belong to LedgerOS.
- External IDs are connector-facing identifiers and should be stable across retries.

## Logging and secrets

Do not log:

- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY`
- any request value that would let another client replay a signed request

Safe logging guidance:

- log the endpoint, status code, and request identifier;
- redact payloads if they may contain personal or financial data;
- avoid logging raw signatures or full secret-bearing headers.

## Versioning guidance

- API routes use the `/api/v1/` prefix when they are intended to be stable external contracts.
- Breaking changes should use a new versioned prefix or a clearly documented migration window.
- Health endpoints are operational endpoints, not connector contracts, and may remain outside the versioned business API.

## See also

- [Connector guide](./connector-guide.md)
- [Epic 10 decision record](./epic-10.md)
- [Implementation epics](./propertyledger-implementation-epics.md)

