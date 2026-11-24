"""Pre-paid customer credit ledger."""

from __future__ import annotations

from billing_svc.models import PricingError


class CreditLedger:
    """Tracks refundable per-tenant credit balances in integer cents."""

    def __init__(self, initial_balances: dict[str, int] | None = None) -> None:
        self._balances: dict[str, int] = dict(initial_balances or {})

    def deposit(self, tenant_id: str, cents: int) -> None:
        if cents < 0:
            raise PricingError("deposit cannot be negative")
        self._balances[tenant_id] = self._balances.get(tenant_id, 0) + cents

    def balance(self, tenant_id: str) -> int:
        return self._balances.get(tenant_id, 0)

    def apply_credit(self, tenant_id: str, requested_cents: int) -> int:
        if requested_cents < 0:
            raise PricingError("requested credit cannot be negative")
        avail = self._balances.get(tenant_id, 0)
        used = min(avail, requested_cents)
        self._balances[tenant_id] = avail - used
        return used

    def refund(self, tenant_id: str, cents: int) -> None:
        if cents > 0:
            self._balances[tenant_id] = self._balances.get(tenant_id, 0) + cents
