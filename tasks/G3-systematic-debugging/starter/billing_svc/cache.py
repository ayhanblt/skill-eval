"""Tenant billing policy store & in-memory cache."""

from __future__ import annotations

from typing import Any

DEFAULT_POLICY: dict[str, Any] = {
    "base_rate_cents": 10_000,
    "discounts": {},
    "feature_credits": [],
    "tax_bps": 800,
}


class TenantPolicyStore:
    """Simulated database repository counting backing reads."""

    def __init__(self, overrides: dict[str, dict[str, Any]] | None = None) -> None:
        self._overrides = overrides or {}
        self.load_calls: int = 0
        self.load_calls_by_tenant: dict[str, int] = {}

    def fetch(self, tenant_id: str) -> dict[str, Any]:
        self.load_calls += 1
        self.load_calls_by_tenant[tenant_id] = self.load_calls_by_tenant.get(tenant_id, 0) + 1
        if tenant_id in self._overrides:
            merged = DEFAULT_POLICY.copy()
            merged.update(self._overrides[tenant_id])
            return merged
        return DEFAULT_POLICY.copy()


class TenantPolicyCache:
    """In-memory per-tenant policy cache."""

    def __init__(self, store: TenantPolicyStore | None = None) -> None:
        self._store = store or TenantPolicyStore()
        self._entries: dict[str, dict[str, Any]] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get_policy(self, tenant_id: str) -> dict[str, Any]:
        if tenant_id in self._entries:
            self.hits += 1
            return self._entries[tenant_id]
        self.misses += 1
        policy = self._store.fetch(tenant_id)
        self._entries[tenant_id] = policy
        return policy

    def invalidate(self, tenant_id: str) -> None:
        self._entries.pop(tenant_id, None)
