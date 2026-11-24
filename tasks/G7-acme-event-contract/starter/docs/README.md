# Acme Engineering Handbook (Order Ingestion Service)

Browse internal architecture specifications, security standards, audit policies, deprecation records, and operational guides below:

## Architecture
- [Error Envelope Standard](architecture/error-handling.md)
- [Event Envelope v2 Specification](architecture/event-envelope-v2.md)
- [Kafka Topic Partitioning Strategy](architecture/kafka-partitioning.md)
- [Transactional Outbox Relayer](architecture/outbox-pattern.md)
- [Schema Registry Conventions](architecture/schema-registry.md)

## Security & Access
- [Idempotency Header & Conflict Semantics](security/idempotency-spec.md)
- [Service-to-Service mTLS Policy](security/tls-mtls-policy.md)
- [Per-Tenant Edge Rate Limits](security/rate-limiting.md)
- [HMAC Signing Key Rotation](security/secret-rotation.md)

## Audit & Compliance
- [Data Retention Schedule](audit/retention-policy.md)
- [Zero-PII Audit Trail Mandate](audit/zero-pii-logging.md)

## Legacy & Superseded Docs
- [Legacy Audit Format v1 (Superseded)](legacy/audit-logging-v1.md)
- [Legacy Event Envelope v1 (Superseded)](legacy/event-envelope-v1.md)
- [Legacy Idempotency Header v1 (Superseded)](legacy/idempotency-v1.md)

## Operations, Runbooks & Onboarding
- [Code Review Checklist](onboarding/code-review-checklist.md)
- [Local Development Setup](onboarding/local-dev.md)
- [Capacity Planning Baseline](ops/capacity-planning.md)
- [Paging Escalation Policy](ops/paging-escalation.md)
- [Prometheus Telemetry Catalog](ops/prometheus-metrics.md)
- [Service Level Objectives](ops/slos.md)
- [Order Lifecycle Overview](product/order-lifecycle.md)
- [Dead-Letter Queue Replay Runbook](runbooks/dlq-replay.md)
- [Incident Triage Guide](runbooks/incident-triage.md)
