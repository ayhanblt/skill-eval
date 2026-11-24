"""Minimal Acme ledger posting helper."""

from __future__ import annotations


def net_balance_cents(entries: list[tuple[str, int]]) -> int:
    """Compute signed net balance from ('CREDIT'|'DEBIT', amount_cents) tuples."""
    total = 0
    for kind, amount in entries:
        if amount < 0:
            raise ValueError("amount_cents must be non-negative")
        if kind == "CREDIT":
            total += amount
        elif kind == "DEBIT":
            total -= amount
        else:
            raise ValueError(f"Unknown entry kind: {kind}")
    return total
