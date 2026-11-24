from __future__ import annotations

from dataclasses import dataclass, field


class PricingError(ValueError):
    """Raised on invalid invoicing arguments or unknown promo/tax schedules."""


class InvoiceTotalMismatchError(ValueError):
    """Raised when settled webhook payment cents do not exactly match invoice total cents."""


@dataclass(frozen=True)
class LineItem:
    code: str
    description: str
    amount_cents: int


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    tenant_id: str
    seats: int
    subtotal_cents: int
    discount_cents: int
    credit_cents: int
    tax_cents: int
    total_cents: int
    applied_promos: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WebhookPayment:
    payment_id: str
    invoice_id: str
    tenant_id: str
    amount_cents: int


@dataclass(frozen=True)
class BatchItem:
    invoice_id: str
    tenant_id: str
    seats: int
    country: str | None = None
    quarter: str = "2026Q1"
    tax_exempt: bool = False
    promo_code: str | None = None
    grant_credit_cents: int = 0
    ledger_credit_cents: int = 0
    payment_cents: int | None = None


@dataclass(frozen=True)
class BatchItemResult:
    invoice_id: str
    tenant_id: str
    status: str
    invoice: Invoice | None = None
    error: str | None = None
