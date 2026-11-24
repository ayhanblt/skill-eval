# Structured Error Envelope Standard

> **Status:** Active (Canonical — Effective 2026-01-01)

Every `4xx` and `5xx` HTTP response MUST return a JSON object with a single top-level `"error"` object — never flat `{"detail": ...}` or plain text:

```json
{
  "error": {
    "code": "ACME_<DOMAIN>_<HTTP>_<REASON>",
    "retryable": false,
    "correlation_id": "req-or-generated-uuid",
    "message": "Human-readable explanation"
  }
}
```

## Canonical Error Codes for Order Events (`EVT`)
- `ACME_EVT_400_MISSING_IDEMPOTENCY_KEY` (`status=400`, `retryable=false`)
- `ACME_EVT_400_INVALID_PAYLOAD` (`status=400`, `retryable=false`)
- `ACME_EVT_409_PAYLOAD_MISMATCH` (`status=409`, `retryable=false`)
- `ACME_EVT_500_INTERNAL_ERROR` (`status=500`, `retryable=true`)
