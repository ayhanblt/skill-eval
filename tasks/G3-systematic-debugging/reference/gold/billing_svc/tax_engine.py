"""Fixed tax schedule resolver (normalized composite cache key + defensive copies)."""

from __future__ import annotations

from typing import Any

from billing_svc.models import PricingError

TAX_SCHEDULES: dict[tuple[str, str], dict[str, Any]] = {
    ("US", "2026Q1"): {"tax_bps": 800, "region": "US", "quarter": "2026Q1"},
    ("US", "2026Q2"): {"tax_bps": 825, "region": "US", "quarter": "2026Q2"},
    ("DE", "2026Q1"): {"tax_bps": 1900, "region": "DE", "quarter": "2026Q1"},
    ("DE", "2026Q2"): {"tax_bps": 2000, "region": "DE", "quarter": "2026Q2"},
    ("CA", "2026Q1"): {"tax_bps": 500, "region": "CA", "quarter": "2026Q1"},
    ("CA", "2026Q2"): {"tax_bps": 550, "region": "CA", "quarter": "2026Q2"},
}


class TaxEngine:
    """Caches resolved tax schedule descriptors per normalized (country, quarter)."""

    def __init__(self) -> None:
        self._schedule_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.lookups: int = 0

    def resolve_rate(
        self, country: str, quarter: str, *, tax_exempt: bool = False
    ) -> dict[str, Any]:
        norm_country = country.strip().upper() if isinstance(country, str) else ""
        norm_quarter = quarter.strip().upper() if isinstance(quarter, str) else ""
        if not norm_country or not norm_quarter:
            raise PricingError("country and quarter must be non-empty")
        if tax_exempt:
            return {
                "tax_bps": 0,
                "region": norm_country,
                "quarter": norm_quarter,
                "tax_exempt": True,
            }
        key = (norm_country, norm_quarter)
        if key not in self._schedule_cache:
            self.lookups += 1
            entry = TAX_SCHEDULES.get(key)
            if entry is None:
                raise ValueError(f"Unknown tax schedule: {norm_country}/{norm_quarter}")
            self._schedule_cache[key] = entry.copy()
        return self._schedule_cache[key].copy()
