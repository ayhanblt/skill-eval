---
name: acme-event-contract
description: Use when implementing or modifying Acme internal domain event handlers, idempotency keys, error envelopes, or audit trail writers in Acme services.
---

# Acme Internal Event Contract

When building or modifying any Acme event-processing endpoint or worker, apply every rule below (canonical reference also lives across `docs/architecture/`, `docs/security/`, and `docs/audit/`):

1. **Envelope & Schema Version (`acme.v2`)**
   - Every persisted or emitted event envelope MUST include `schema_version: "acme.v2"`, `event_id` (UUIDv4), `correlation_id`, `tenant_id`, and `occurred_at_utc` (RFC 3339 ending in `Z`, never local offset).
2. **Idempotency Header & Conflict Semantics**
   - Inbound mutation requests require header `X-Acme-Idempotency-Key` (never generic `Idempotency-Key`).
   - Compute SHA-256 over canonical JSON payload (`sort_keys=True`, compact separators).
   - Same key + identical payload hash → return original response with header `X-Acme-Replayed: true`.
   - Same key + different payload hash → reject with HTTP `409` and Acme error code `ACME_EVT_409_PAYLOAD_MISMATCH`.
3. **Structured Error Envelope**
   - All 4xx/5xx responses MUST follow `{ "error": { "code": "ACME_<DOMAIN>_<HTTP>_<REASON>", "retryable": bool, "correlation_id": str, "message": str } }`.
4. **Zero-PII Audit Log**
   - Append every accepted and rejected mutation to the append-only audit log (`audit_events` table or `audit.jsonl`) with `actor_id`, `action`, `outcome`, `payload_sha256`, and `correlation_id`.
   - NEVER log raw card numbers, emails, phone numbers, authorization headers, or unredacted request payloads.
5. **Verification Checklist**
   - Verify duplicate replay, payload mismatch (`409`), missing header (`400`), PII-redacted audit entry, and `Z`-suffixed UTC timestamp before finishing.
