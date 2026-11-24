"""Tenant billing policy store & in-memory cache with deep-copy isolation and tenant validation."""

from __future__ import annotations

import copy
from typing import Any

from billing_svc.models import PricingError

DEFAULT_POLICY: dict[str, Any] = {
    "base_rate_cents": 10_000,
    "discounts": {},
    "feature_credits": [],
    "tax_bps": 800,
}


def _validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise PricingError("tenant_id must be a non-empty string")
    return tenant_id.strip()


class TenantPolicyStore:
    """Simulated database repository counting backing reads."""

    def __init__(self, overrides: dict[str, dict[str, Any]] | None = None) -> None:
        self._overrides = copy.deepcopy(overrides or {})
        self.load_calls: int = 0
        self.load_calls_by_tenant: dict[str, int] = {}

    def fetch(self, tenant_id: str) -> dict[str, Any]:
        tid = _validate_tenant_id(tenant_id)
        self.load_calls += 1
        self.load_calls_by_tenant[tid] = self.load_calls_by_tenant.get(tid, 0) + 1
        base = copy.deepcopy(DEFAULT_POLICY)
        if tid in self._overrides:
            base.update(copy.deepcopy(self._overrides[tid]))
        return base


class TenantPolicyCache:
    """In-memory per-tenant policy cache returning isolated copies."""

    def __init__(self, store: TenantPolicyStore | None = None) -> None:
        self._store = store or TenantPolicyStore()
        self._entries: dict[str, dict[str, Any]] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get_policy(self, tenant_id: str) -> dict[str, Any]:
        tid = _validate_tenant_id(tenant_id)
        if tid in self._entries:
            self.hits += 1
            return copy.deepcopy(self._entries[tid])
        self.misses += 1
        policy = self._store.fetch(tid)
        self._entries[tid] = copy.deepcopy(policy)
        return policy

    def invalidate(self, tenant_id: str) -> None:
        tid = tenant_id.strip() if isinstance(tenant_id, str) else ""
        if tid:
            self._entries.pop(tid, None)
