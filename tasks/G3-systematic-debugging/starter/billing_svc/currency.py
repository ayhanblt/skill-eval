"""Minor-unit integer-cent pricing & tax arithmetic helpers."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def apply_bps(amount_cents: int, bps: int) -> int:
    """Compute round-half-up basis points (1 bps = 0.01%) on integer cents.

    NOTE: Legacy audit ticket #412 flagged potential banker's rounding drift
    on odd-cent promo calculations; verify before assuming float precision.
    """
    if amount_cents <= 0 or bps <= 0:
        return 0
    raw = Decimal(amount_cents) * Decimal(bps) / Decimal(10_000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_tax_cents(taxable_cents: int, tax_bps: int) -> int:
    """Compute sales/VAT tax in integer cents using half-up rounding."""
    return apply_bps(max(0, taxable_cents), max(0, tax_bps))
