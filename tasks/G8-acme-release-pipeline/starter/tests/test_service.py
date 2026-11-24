from service.ledger import net_balance_cents
import pytest


def test_net_balance_credits_and_debits() -> None:
    assert net_balance_cents([("CREDIT", 5000), ("DEBIT", 1250)]) == 3750


def test_negative_amount_rejected() -> None:
    with pytest.raises(ValueError):
        net_balance_cents([("CREDIT", -10)])
