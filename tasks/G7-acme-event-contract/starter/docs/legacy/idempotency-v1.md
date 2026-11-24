# Legacy Idempotency Header v1 (Deprecated)

> **Status:** Deprecated / Superseded by `security/idempotency-spec.md` (Retired 2025-12-31)

Prior gateways accepted the generic `Idempotency-Key` header and hashed raw HTTP body bytes. All active Acme services MUST reject generic `Idempotency-Key` and follow `security/idempotency-spec.md`.
