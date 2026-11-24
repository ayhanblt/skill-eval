# Order Ingestion SLOs

- P99 ingest latency target: < 25 ms per event.
- Durability: idempotency records and accepted events are committed before returning `201`.
