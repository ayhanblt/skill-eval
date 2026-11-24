from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


class PricingValidationError(ValueError):
    """Raised when contract, catalog, discount, credit, adjustment, seat, or usage inputs are invalid."""


@dataclass(frozen=True)
class VolumeTier:
    up_to: int | None
    unit_price: Decimal


@dataclass(frozen=True)
class SkuCatalogEntry:
    sku: str
    tiers: tuple[VolumeTier, ...]
    taxable: bool = True
    tier_mode: Literal["GRADUATED", "VOLUME"] = "GRADUATED"
    included_units: int = 0


@dataclass(frozen=True)
class SeatSegment:
    seats: int
    monthly_seat_price: Decimal
    active_days: int
    taxable: bool = True


@dataclass(frozen=True)
class Adjustment:
    code: str
    amount: Decimal
    taxable: bool = True


@dataclass(frozen=True)
class DiscountRule:
    code: str
    kind: Literal["PCT", "FIXED"]
    value: Decimal
    stackable: bool = False
    starts_on: date | None = None
    ends_on: date | None = None
    target_sku: str | None = None
    min_subtotal: Decimal = Decimal("0.00")
    max_discount_amount: Decimal | None = None


@dataclass(frozen=True)
class PrepaidCredit:
    credit_id: str
    amount: Decimal
    expires_on: date


@dataclass(frozen=True)
class UsageRecord:
    sku: str
    quantity: int


@dataclass(frozen=True)
class Contract:
    contract_id: str
    catalog: dict[str, SkuCatalogEntry]
    monthly_minimum: Decimal = Decimal("0.00")
    billing_period_days: int = 30
    proration_days: int = 30
    discounts: tuple[DiscountRule, ...] = ()
    credits: tuple[PrepaidCredit, ...] = ()
    tax_rate_pct: Decimal = Decimal("0.00")
    tax_exempt: bool = False
    seat_segments: tuple[SeatSegment, ...] = ()
    adjustments: tuple[Adjustment, ...] = ()
    credit_cap_pct: Decimal = Decimal("100")


@dataclass(frozen=True)
class InvoiceLineItem:
    sku: str
    quantity: int
    amount: Decimal
    taxable: bool


@dataclass(frozen=True)
class InvoiceQuote:
    contract_id: str
    line_items: tuple[InvoiceLineItem, ...]
    usage_subtotal: Decimal
    minimum_true_up: Decimal
    gross_subtotal: Decimal
    non_stackable_discount_code: str | None
    discount_total: Decimal
    post_discount_subtotal: Decimal
    credits_applied: Decimal
    remaining_credits: tuple[PrepaidCredit, ...]
    net_taxable_subtotal: Decimal
    tax_amount: Decimal
    total_due: Decimal
