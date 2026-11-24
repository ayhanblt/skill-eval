"""Multi-tenant batch invoicing and payment reconciliation runner."""

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
    """Processes batches of tenant invoices against shared cache, tax engine, and ledger."""

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

    def process_batch(self, items: list[BatchItem]) -> list[BatchItemResult]:
        results: list[BatchItemResult] = []
        for idx, item in enumerate(items, start=1):
            debited = 0
            try:
                if item.ledger_credit_cents > 0:
                    debited = self.ledger.apply_credit(item.tenant_id, item.ledger_credit_cents)
                inv = generate_invoice(
                    item.invoice_id,
                    item.tenant_id,
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
                        invoice_id=item.invoice_id,
                        tenant_id=item.tenant_id,
                        amount_cents=item.payment_cents,
                    )
                    reconcile_payment(inv, pay)
                results.append(
                    BatchItemResult(
                        invoice_id=item.invoice_id,
                        tenant_id=item.tenant_id,
                        status="reconciled" if item.payment_cents is not None else "invoiced",
                        invoice=inv,
                    )
                )
            except (PricingError, ValueError, InvoiceTotalMismatchError) as exc:
                results.append(
                    BatchItemResult(
                        invoice_id=item.invoice_id,
                        tenant_id=item.tenant_id,
                        status="failed",
                        error=str(exc),
                    )
                )
        return results
