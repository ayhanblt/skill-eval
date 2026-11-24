from pathlib import Path
from acme_orders.handler import AcmeOrderEventService


def test_service_initializes(tmp_path: Path) -> None:
    svc = AcmeOrderEventService(tmp_path)
    assert svc.storage.count_events() == 0
