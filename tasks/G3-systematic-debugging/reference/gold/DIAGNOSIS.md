# Incident #4812 — Root Cause Analysis

## Four Interacting Root Causes Found
1. **Shared mutable policy references (`billing_svc/cache.py` & `billing_svc/pricing.py`)**:
   `TenantPolicyStore.fetch()` and `TenantPolicyCache.get_policy()` returned shallow copies of `DEFAULT_POLICY` and cached entries, aliasing nested `discounts` dicts and `feature_credits` lists across tenants. `pricing.py` mutated `policy["discounts"]` and `policy["feature_credits"]` in place, leaking one-off promos and credits between tenants and repeated invoices.
   Fix: `copy.deepcopy(...)` on store/cache boundaries + local dict/list construction in `pricing.py`.

2. **Tax schedule key omission, normalization & shared-dict mutation (`billing_svc/tax_engine.py` & `billing_svc/pricing.py`)**:
   `TaxEngine._schedule_cache` was keyed solely by raw `country` (omitting `quarter` and failing to strip/uppercase mixed-case inputs like `" us "`/`"2026q2"`) and returned a cached mutable dict that `pricing.py` mutated (`sched["tax_bps"] = 0`) when `tax_exempt=True`, corrupting subsequent tax lookups across quarters and exempt vs taxable customers.
   Fix: composite normalized key `(country.strip().upper(), quarter.strip().upper())`, defensive `.copy()` returns, and dedicated `tax_exempt` short-circuit without cache mutation.

3. **Non-atomic ledger debit & unrefunded excess credit (`billing_svc/batch_runner.py`)**:
   `BatchRunner.process_batch()` debited the full `item.ledger_credit_cents` from `CreditLedger` up front, neither refunding on `PricingError`/`ValueError`/`InvoiceTotalMismatchError` failures nor refunding unused excess when non-ledger `feature_credits` / `grant_credit_cents` or promo discounts reduced the post-discount payable amount below the debited amount.
   Fix: refund `debited` on exception rollback AND compute `used_ledger = max(0, min(debited, inv.credit_cents - non_ledger))` and refund `debited - used_ledger` on success.

4. **Missing webhook idempotency & multi-layer input validation (`billing_svc/batch_runner.py`, `billing_svc/webhook.py`, `billing_svc/cache.py`, `billing_svc/ledger.py`, `billing_svc/pricing.py`)**:
   Replaying a previously reconciled `invoice_id` re-debited `CreditLedger`, and unvalidated entry/inner boundaries let whitespace `tenant_id` (`"   "`) and unnormalized `country`/`quarter` strings pollute cache/ledger keys or crash downstream.
   Fix: `BatchRunner` caches reconciled outcomes by `invoice_id` so duplicate deliveries return idempotently without double-debiting (while previously failed items remain retryable), AND defense-in-depth validation rejects blank `tenant_id`/`invoice_id`/`country`/`quarter` across `webhook.parse_batch_payload`, `TenantPolicyStore`/`TenantPolicyCache`, `CreditLedger`, and `generate_invoice`.

## Rejected Hypotheses (Red Herrings)
- `billing_svc/currency.py` half-up integer-cent Decimal rounding is exact and required by spec.
- `billing_svc/reconciler.py` exact integer-cent comparison (`invoice.total_cents != payment.amount_cents`) is an intentional financial invariant and must NOT be relaxed with tolerance windows.
