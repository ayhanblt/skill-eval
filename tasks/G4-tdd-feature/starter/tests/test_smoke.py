from datetime import date
from decimal import Decimal

from pricing_engine.models import Contract, SkuCatalogEntry, VolumeTier


def test_models_construct_cleanly() -> None:
    c = Contract(
        contract_id="c-smoke",
        catalog={
            "API_CALLS": SkuCatalogEntry(
                sku="API_CALLS",
                tiers=(VolumeTier(up_to=1000, unit_price=Decimal("0.10")), VolumeTier(up_to=None, unit_price=Decimal("0.05"))),
            )
        },
    )
    assert c.contract_id == "c-smoke"
    assert date(2026, 1, 15).year == 2026
