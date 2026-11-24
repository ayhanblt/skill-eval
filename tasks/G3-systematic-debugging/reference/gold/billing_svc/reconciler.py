"""Webhook payment reconciliation (exact minor-unit verification)."""

from __future__ import annotations

from billing_svc.models import Invoice, InvoiceTotalMismatchError, WebhookPayment


def reconcile_payment(invoice: Invoice, payment: WebhookPayment) -> str:
    """Verify settled payment exactly equals invoiced cents."""
    if invoice.invoice_id != payment.invoice_id or invoice.tenant_id != payment.tenant_id:
        raise InvoiceTotalMismatchError(
            f"Metadata mismatch for invoice={invoice.invoice_id} tenant={invoice.tenant_id}"
        )
    if invoice.total_cents != payment.amount_cents:
        raise InvoiceTotalMismatchError(
            f"Exact cent mismatch on invoice={invoice.invoice_id} tenant={invoice.tenant_id}: "
            f"expected {invoice.total_cents}, got {payment.amount_cents}"
        )
    return "reconciled"
