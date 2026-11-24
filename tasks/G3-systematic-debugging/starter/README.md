# Acme Multi-Tenant Billing Service (`billing_svc`)

## Layout
- `billing_svc/models.py`: Data models (`LineItem`, `Invoice`, `WebhookPayment`, `BatchItem`, `BatchItemResult`, `PricingError`, `InvoiceTotalMismatchError`).
- `billing_svc/currency.py`: Minor-unit integer-cent discount and tax helpers.
- `billing_svc/cache.py`: `TenantPolicyStore` and `TenantPolicyCache`.
- `billing_svc/tax_engine.py`: Jurisdiction & quarterly tax schedule resolver (`TaxEngine`).
- `billing_svc/pricing.py`: `generate_invoice(...)` calculating seat subtotal, promo discount, feature credits, and tax.
- `billing_svc/ledger.py`: Pre-paid per-tenant credit ledger (`CreditLedger`).
- `billing_svc/webhook.py`: Webhook batch payload parser (`parse_batch_payload(...)`).
- `billing_svc/batch_runner.py`: End-to-end batch invoice + reconciliation runner (`BatchRunner`).
- `billing_svc/reconciler.py`: `reconcile_payment(...)` comparing webhook payments against invoice totals.
- `incidents/incident_4812.log`: Production logs and finance alerts from Incident #4812.
- `tests/test_existing.py`: Passing baseline unit tests.
- `tests/test_bug_repro.py`: Minimal failing bug reproducer from Incident #4812.

## Deliverables
1. Root-cause fix(es) inside `billing_svc/`.
2. Regression test(s) under `tests/`.
3. Root-cause analysis report in `DIAGNOSIS.md`.
