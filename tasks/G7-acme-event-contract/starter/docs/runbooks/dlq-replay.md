# Dead-Letter Queue Replay Runbook

> **Status:** Active (Runbook)

Inspect poisoned messages in `orders.dlq` before re-submitting with original `X-Acme-Idempotency-Key` headers.
