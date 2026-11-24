"""Jurisdiction and quarterly tax schedule resolver."""

from __future__ import annotations

from typing import Any

TAX_SCHEDULES: dict[tuple[str, str], dict[str, Any]] = {
    ("US", "2026Q1"): {"tax_bps": 800, "region": "US", "quarter": "2026Q1"},
    ("US", "2026Q2"): {"tax_bps": 825, "region": "US", "quarter": "2026Q2"},
    ("DE", "2026Q1"): {"tax_bps": 1900, "region": "DE", "quarter": "2026Q1"},
    ("DE", "2026Q2"): {"tax_bps": 2000, "region": "DE", "quarter": "2026Q2"},
    ("CA", "2026Q1"): {"tax_bps": 500, "region": "CA", "quarter": "2026Q1"},
    ("CA", "2026Q2"): {"tax_bps": 550, "region": "CA", "quarter": "2026Q2"},
}


class TaxEngine:
    """Caches resolved tax schedule descriptors per jurisdiction."""

    def __init__(self) -> None:
        self._schedule_cache: dict[str, dict[str, Any]] = {}
        self.lookups: int = 0

    def resolve_rate(
        self, country: str, quarter: str, *, tax_exempt: bool = False
    ) -> dict[str, Any]:
        key = country
        if key not in self._schedule_cache:
            self.lookups += 1
            entry = TAX_SCHEDULES.get((country, quarter))
            if entry is None:
                raise ValueError(f"Unknown tax schedule: {country}/{quarter}")
            self._schedule_cache[key] = entry.copy()
        return self._schedule_cache[key]
