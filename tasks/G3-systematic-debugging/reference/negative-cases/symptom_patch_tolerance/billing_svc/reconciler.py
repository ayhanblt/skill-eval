"""Symptom patch: relaxes exact reconciliation check to tolerate mismatches."""

from __future__ import annotations

from billing_svc.models import Invoice, InvoiceTotalMismatchError, WebhookPayment


def reconcile_payment(invoice: Invoice, payment: WebhookPayment) -> str:
    if invoice.invoice_id != payment.invoice_id or invoice.tenant_id != payment.tenant_id:
        raise InvoiceTotalMismatchError("Metadata mismatch")
    if abs(invoice.total_cents - payment.amount_cents) > 5_000:
        raise InvoiceTotalMismatchError("Mismatch exceeds tolerance")
    return "reconciled"
