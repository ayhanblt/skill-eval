# Idempotency Header & Conflict Semantics

> **Status:** Active (Canonical — Effective 2026-01-01)

1. **Vendor-Specific Header Name**:
   - Inbound mutation requests MUST supply `X-Acme-Idempotency-Key` (case-insensitive header lookup).
   - Generic `Idempotency-Key` MUST NOT be accepted as a fallback — reject with HTTP `400` and `ACME_EVT_400_MISSING_IDEMPOTENCY_KEY`.

2. **Canonical Payload Hash**:
   - Parse the JSON request body and compute SHA-256 over canonical JSON:
     ```python
     canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
     payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
     ```
   - Whitespace or JSON object key reordering MUST produce the identical hash.

3. **Replay vs Conflict**:
   - **New key**: process, persist event envelope + idempotency record (`payload_sha256`, original status `201`, original body), return HTTP `201`.
   - **Same key + identical `payload_sha256`**: return the EXACT original response status and JSON body plus header `X-Acme-Replayed: true`. Never persist a duplicate event.
   - **Same key + different `payload_sha256`**: reject with HTTP `409` and structured error code `ACME_EVT_409_PAYLOAD_MISMATCH`.
