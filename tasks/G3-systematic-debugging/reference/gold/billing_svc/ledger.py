"""Pre-paid customer credit ledger with tenant validation."""

from __future__ import annotations

from billing_svc.models import PricingError


def _clean_tenant(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise PricingError("tenant_id must be a non-empty string")
    return tenant_id.strip()


class CreditLedger:
    """Tracks refundable per-tenant credit balances in integer cents."""

    def __init__(self, initial_balances: dict[str, int] | None = None) -> None:
        self._balances: dict[str, int] = dict(initial_balances or {})

    def deposit(self, tenant_id: str, cents: int) -> None:
        tid = _clean_tenant(tenant_id)
        if cents < 0:
            raise PricingError("deposit cannot be negative")
        self._balances[tid] = self._balances.get(tid, 0) + cents

    def balance(self, tenant_id: str) -> int:
        tid = _clean_tenant(tenant_id)
        return self._balances.get(tid, 0)

    def apply_credit(self, tenant_id: str, requested_cents: int) -> int:
        tid = _clean_tenant(tenant_id)
        if requested_cents < 0:
            raise PricingError("requested credit cannot be negative")
        avail = self._balances.get(tid, 0)
        used = min(avail, requested_cents)
        self._balances[tid] = avail - used
        return used

    def refund(self, tenant_id: str, cents: int) -> None:
        tid = _clean_tenant(tenant_id)
        if cents > 0:
            self._balances[tid] = self._balances.get(tid, 0) + cents
