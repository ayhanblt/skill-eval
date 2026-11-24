# Event Envelope v2 (`acme.v2`)

> **Status:** Active (Canonical — Effective 2026-01-01)

Every persisted and returned domain event envelope MUST conform strictly to `acme.v2`:

- `schema_version`: exact literal string `"acme.v2"`
- `event_id`: freshly generated UUIDv4 string (`str(uuid.uuid4())`)
- `correlation_id`: extracted from `X-Correlation-Id` request header (case-insensitive); if absent or blank, generate a UUIDv4 string
- `tenant_id`: non-empty string from the request payload
- `order_id`: non-empty string from the request payload
- `amount_cents`: positive integer from the request payload
- `occurred_at_utc`: RFC 3339 UTC timestamp string ending strictly with `"Z"` (e.g., `2026-11-23T14:05:11Z` — NEVER emit `+00:00` or naive timestamps)
- `event_type`: `"order.submitted"` (or payload `event_type` if provided, default `"order.submitted"`)

Required inbound JSON fields: `tenant_id` (non-empty str), `order_id` (non-empty str), `amount_cents` (int > 0, not bool). Invalid/missing fields or malformed JSON MUST fail with HTTP `400` and code `ACME_EVT_400_INVALID_PAYLOAD`.
