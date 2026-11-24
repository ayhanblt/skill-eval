# Zero-PII Audit Trail Mandate

> **Status:** Active (Canonical — Effective 2026-01-01)

Every inbound mutation attempt — **both accepted/replayed AND rejected (`400`/`409`)** — MUST append one structured record to the append-only audit log (`audit.jsonl` and `audit_events` table via `OrderStorage.append_audit`).

## Required Audit Fields
- `actor_id`: extracted from `X-Actor-Id` header (default `"anonymous"`)
- `action`: `"order.ingest"`
- `outcome`: `"accepted"`, `"replayed"`, or `"rejected"`
- `payload_sha256`: canonical JSON SHA-256 (or raw-bytes SHA-256 if body is unparseable JSON)
- `correlation_id`: matching response `correlation_id`
- `error_code`: `null` on success/replay, or `"ACME_EVT_..."` on rejection
- `recorded_at_utc`: RFC 3339 UTC ending in `"Z"`

## Strict Zero-PII Prohibition
NEVER write raw `customer_email`, `email`, `phone`, `card_number`, `Authorization` headers, or unredacted request payloads to `audit.jsonl` or `audit_events`.
