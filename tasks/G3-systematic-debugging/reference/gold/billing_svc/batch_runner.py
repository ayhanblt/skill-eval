"""Multi-tenant batch invoicing and reconciliation runner with atomic ledger rollback & idempotency."""

from __future__ import annotations

from billing_svc.cache import TenantPolicyCache
from billing_svc.ledger import CreditLedger
from billing_svc.models import (
    BatchItem,
    BatchItemResult,
    InvoiceTotalMismatchError,
    PricingError,
    WebhookPayment,
)
from billing_svc.pricing import generate_invoice
from billing_svc.reconciler import reconcile_payment
from billing_svc.tax_engine import TaxEngine


class BatchRunner:
    """Processes batches of tenant invoices; ensures idempotency and exact ledger accounting."""

    def __init__(
        self,
        *,
        cache: TenantPolicyCache | None = None,
        tax_engine: TaxEngine | None = None,
        ledger: CreditLedger | None = None,
    ) -> None:
        self.cache = cache or TenantPolicyCache()
        self.tax_engine = tax_engine or TaxEngine()
        self.ledger = ledger or CreditLedger()
        self._reconciled_results: dict[str, BatchItemResult] = {}

    def process_batch(self, items: list[BatchItem]) -> list[BatchItemResult]:
        results: list[BatchItemResult] = []
        for idx, item in enumerate(items, start=1):
            inv_id = item.invoice_id.strip() if isinstance(item.invoice_id, str) else ""
            if inv_id and inv_id in self._reconciled_results:
                results.append(self._reconciled_results[inv_id])
                continue

            debited = 0
            tid = item.tenant_id.strip() if isinstance(item.tenant_id, str) else ""
            try:
                if not inv_id:
                    raise PricingError("invoice_id must be a non-empty string")
                if not tid:
                    raise PricingError("tenant_id must be a non-empty string")

                policy = self.cache.get_policy(tid)
                non_ledger = sum(int(c) for c in (policy.get("feature_credits") or [])) + max(
                    0, int(item.grant_credit_cents)
                )

                if item.ledger_credit_cents > 0:
                    debited = self.ledger.apply_credit(tid, item.ledger_credit_cents)

                inv = generate_invoice(
                    inv_id,
                    tid,
                    item.seats,
                    promo_code=item.promo_code,
                    grant_credit_cents=item.grant_credit_cents,
                    ledger_credit_cents=debited,
                    country=item.country,
                    quarter=item.quarter,
                    tax_exempt=item.tax_exempt,
                    cache=self.cache,
                    tax_engine=self.tax_engine,
                )
                if item.payment_cents is not None:
                    pay = WebhookPayment(
                        payment_id=f"batch-pay-{idx}",
                        invoice_id=inv_id,
                        tenant_id=tid,
                        amount_cents=item.payment_cents,
                    )
                    reconcile_payment(inv, pay)

                used_ledger = max(0, min(debited, inv.credit_cents - non_ledger))
                excess = debited - used_ledger
                if excess > 0:
                    self.ledger.refund(tid, excess)

                outcome = BatchItemResult(
                    invoice_id=inv_id,
                    tenant_id=tid,
                    status="reconciled" if item.payment_cents is not None else "invoiced",
                    invoice=inv,
                )
                if outcome.status == "reconciled":
                    self._reconciled_results[inv_id] = outcome
                results.append(outcome)
            except (PricingError, ValueError, InvoiceTotalMismatchError) as exc:
                if debited > 0 and tid:
                    self.ledger.refund(tid, debited)
                results.append(
                    BatchItemResult(
                        invoice_id=item.invoice_id,
                        tenant_id=item.tenant_id,
                        status="failed",
                        error=str(exc),
                    )
                )
        return results
