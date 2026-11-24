import json
from pathlib import Path
from acme_orders.handler import AcmeOrderEventService


def test_replay_conflict_missing_header_and_zero_pii_audit(tmp_path: Path) -> None:
    svc = AcmeOrderEventService(tmp_path)
    bad = svc.handle_request({"Idempotency-Key": "generic"}, b'{"tenant_id":"t1","order_id":"o1","amount_cents":100}')
    assert bad.status == 400
    assert bad.body["error"]["code"] == "ACME_EVT_400_MISSING_IDEMPOTENCY_KEY"

    b1 = b'{"tenant_id":"t1","order_id":"o1","amount_cents":100,"customer_email":"secret@acme.io"}'
    b2 = b'{"amount_cents":100,"customer_email":"secret@acme.io","order_id":"o1","tenant_id":"t1"}'
    r1 = svc.handle_request({"X-Acme-Idempotency-Key": "k1", "Authorization": "Bearer topsecret"}, b1)
    assert r1.status == 201 and r1.body["schema_version"] == "acme.v2" and r1.body["occurred_at_utc"].endswith("Z")

    r2 = svc.handle_request({"X-Acme-Idempotency-Key": "k1"}, b2)
    assert r2.headers.get("X-Acme-Replayed") == "true"
    assert r2.body["event_id"] == r1.body["event_id"]

    r3 = svc.handle_request({"X-Acme-Idempotency-Key": "k1"}, b'{"tenant_id":"t1","order_id":"o1","amount_cents":999}')
    assert r3.status == 409
    assert r3.body["error"]["code"] == "ACME_EVT_409_PAYLOAD_MISMATCH"

    raw_audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "secret@acme.io" not in raw_audit
    assert "topsecret" not in raw_audit
