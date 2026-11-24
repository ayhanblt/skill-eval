"""HTTP-style order event handler."""

from __future__ import annotations

from pathlib import Path

from acme_orders.models import HttpResponse
from acme_orders.storage import OrderStorage


class AcmeOrderEventService:
    def __init__(self, data_dir: Path | str) -> None:
        self.storage = OrderStorage(data_dir)

    def handle_request(self, headers: dict[str, str], body: bytes) -> HttpResponse:
        raise NotImplementedError("Implement handle_request according to docs/")
