"""Hidden deterministic grader for G7-acme-event-contract."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

CONTAINER_SCRIPT = r"""
import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, "/workspace")
OUT_DIR = Path("/grade_out")

PII_SENTINELS = [
    "alice.secret@example.org",
    "+1-555-0199",
    "4111222233334444",
    "sk-secret-bearer-token-999",
]


def is_uuid4(val):
    try:
        u = uuid.UUID(str(val))
        return u.version == 4
    except Exception:
        return False


def is_z_utc(val):
    return isinstance(val, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", val))


def run_hidden():
    from acme_orders.handler import AcmeOrderEventService

    results = {}

    def check(name, fn):
        try:
            fn()
            results[name] = {"passed": True, "detail": "ok"}
        except Exception as exc:
            results[name] = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}

    def t_valid_envelope_and_utc():
        d = Path(tempfile.mkdtemp())
        svc = AcmeOrderEventService(d)
        body = json.dumps({
            "tenant_id": "t-100",
            "order_id": "ord-1",
            "amount_cents": 4999,
            "customer_email": PII_SENTINELS[0],
        }).encode()
        resp = svc.handle_request(
            {
                "X-Acme-Idempotency-Key": "idem-1",
                "X-Correlation-Id": "corr-abc",
                "X-Actor-Id": "svc-checkout",
                "Authorization": f"Bearer {PII_SENTINELS[3]}",
            },
            body,
        )
        assert resp.status in (200, 201), resp
        env = resp.body
        assert env.get("schema_version") == "acme.v2", env
        assert is_uuid4(env.get("event_id")), env
        assert env.get("correlation_id") == "corr-abc", env
        assert env.get("tenant_id") == "t-100", env
        assert is_z_utc(env.get("occurred_at_utc")), env
        assert svc.storage.count_events() == 1

    def t_missing_and_generic_idempotency_key():
        d = Path(tempfile.mkdtemp())
        svc = AcmeOrderEventService(d)
        body = json.dumps({"tenant_id": "t-1", "order_id": "o-1", "amount_cents": 100}).encode()
        # Generic Idempotency-Key MUST be rejected!
        resp = svc.handle_request({"Idempotency-Key": "generic-1", "X-Correlation-Id": "corr-400"}, body)
        assert resp.status == 400, resp
        err = (resp.body or {}).get("error") or {}
        assert re.match(r"^ACME_EVT_400_[A-Z0-9_]+$", str(err.get("code") or "")), resp.body
        assert isinstance(err.get("retryable"), bool), resp.body
        assert err.get("correlation_id") == "corr-400", resp.body
        assert err.get("message"), resp.body

    def t_canonical_replay_and_restart_persistence():
        d = Path(tempfile.mkdtemp())
        svc1 = AcmeOrderEventService(d)
        b1 = b'{\n  "tenant_id": "t-2",\n  "order_id": "ord-2",\n  "amount_cents": 2500\n}'
        b2 = b'{"amount_cents":2500,"order_id":"ord-2","tenant_id":"t-2"}'
        r1 = svc1.handle_request({"x-acme-idempotency-key": "idem-canon", "X-Correlation-Id": "c1"}, b1)
        assert r1.status in (200, 201), r1
        # Simulate restart with fresh instance
        svc2 = AcmeOrderEventService(d)
        r2 = svc2.handle_request({"X-Acme-Idempotency-Key": "idem-canon", "X-Correlation-Id": "c2"}, b2)
        assert r2.status == r1.status, r2
        hdrs_low = {k.lower(): v for k, v in r2.headers.items()}
        assert hdrs_low.get("x-acme-replayed", "").lower() == "true", r2.headers
        assert r2.body.get("event_id") == r1.body.get("event_id"), (r1.body, r2.body)
        assert svc2.storage.count_events() == 1

    def t_conflict_409_payload_mismatch():
        d = Path(tempfile.mkdtemp())
        svc = AcmeOrderEventService(d)
        b1 = json.dumps({"tenant_id": "t-3", "order_id": "ord-3", "amount_cents": 1000}).encode()
        b2 = json.dumps({"tenant_id": "t-3", "order_id": "ord-3", "amount_cents": 9999}).encode()
        r1 = svc.handle_request({"X-Acme-Idempotency-Key": "idem-conflict"}, b1)
        assert r1.status in (200, 201), r1
        r2 = svc.handle_request({"X-Acme-Idempotency-Key": "idem-conflict", "X-Correlation-Id": "c-conf"}, b2)
        assert r2.status == 409, r2
        err = (r2.body or {}).get("error") or {}
        assert err.get("code") == "ACME_EVT_409_PAYLOAD_MISMATCH", r2.body
        assert err.get("correlation_id") == "c-conf", r2.body
        assert err.get("retryable") is False, r2.body

    def t_invalid_payload_400():
        d = Path(tempfile.mkdtemp())
        svc = AcmeOrderEventService(d)
        for bad in [b"{bad json", json.dumps({"tenant_id": "t", "order_id": "o", "amount_cents": -5}).encode()]:
            r = svc.handle_request({"X-Acme-Idempotency-Key": "idem-bad"}, bad)
            assert r.status == 400, r
            err = (r.body or {}).get("error") or {}
            assert str(err.get("code") or "").startswith("ACME_EVT_400_"), r.body

    def t_zero_pii_audit_accepted_and_rejected():
        d = Path(tempfile.mkdtemp())
        svc = AcmeOrderEventService(d)
        pii_payload = json.dumps({
            "tenant_id": "t-pii",
            "order_id": "ord-pii",
            "amount_cents": 5000,
            "customer_email": PII_SENTINELS[0],
            "phone": PII_SENTINELS[1],
            "card_number": PII_SENTINELS[2],
        }).encode()
        # 1 accepted, 1 rejected (missing header), 1 rejected (409 conflict)
        svc.handle_request(
            {"X-Acme-Idempotency-Key": "pii-1", "X-Actor-Id": "act-1", "Authorization": f"Bearer {PII_SENTINELS[3]}"},
            pii_payload,
        )
        svc.handle_request(
            {"Idempotency-Key": "wrong", "X-Actor-Id": "act-2", "Authorization": f"Bearer {PII_SENTINELS[3]}"},
            pii_payload,
        )
        svc.handle_request(
            {"X-Acme-Idempotency-Key": "pii-1", "X-Actor-Id": "act-3"},
            json.dumps({"tenant_id": "t-pii", "order_id": "ord-pii", "amount_cents": 1}).encode(),
        )
        audit_file = d / "audit.jsonl"
        assert audit_file.is_file(), "Missing audit.jsonl"
        raw_audit = audit_file.read_text(encoding="utf-8")
        lines = [json.loads(ln) for ln in raw_audit.splitlines() if ln.strip()]
        assert len(lines) >= 3, f"Expected >=3 audit entries (accepted + rejected), got {len(lines)}"
        for rec in lines:
            for k in ("actor_id", "action", "outcome", "payload_sha256", "correlation_id"):
                assert rec.get(k), f"Audit missing {k}: {rec}"
            assert is_z_utc(rec.get("recorded_at_utc")), rec
        for sentinel in PII_SENTINELS:
            assert sentinel not in raw_audit, f"PII sentinel leaked into audit.jsonl: {sentinel}"

    check("h_valid_envelope_and_z_utc", t_valid_envelope_and_z_utc if False else t_valid_envelope_and_utc)
    check("h_missing_and_generic_idempotency_key", t_missing_and_generic_idempotency_key)
    check("h_canonical_replay_and_restart", t_canonical_replay_and_restart_persistence)
    check("h_conflict_409", t_conflict_409_payload_mismatch)
    check("h_invalid_payload_400", t_invalid_payload_400)
    check("h_zero_pii_audit_every_mutation", t_zero_pii_audit_accepted_and_rejected)
    return results


def main():
    cand = subprocess.run(
        ["/opt/skilleval-py/bin/python", "-m", "pytest", "-q"],
        cwd="/workspace",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    hidden = run_hidden()
    test_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in Path("/workspace/tests").glob("test_*.py")
    ) if Path("/workspace/tests").is_dir() else ""
    has_contract_tests = (
        "ACME_EVT_409_PAYLOAD_MISMATCH" in test_text
        and "X-Acme-Replayed" in test_text
        and "audit" in test_text.lower()
    )
    payload = {
        "cand_tests_ok": cand.returncode == 0,
        "cand_tests_out": cand.stdout[-600:],
        "has_contract_tests": has_contract_tests,
        "hidden": hidden,
    }
    (OUT_DIR / "grade_payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = deliverables, task_dir
    if not (workspace / "acme_orders" / "handler.py").is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G7-acme-event-contract",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
        )

    with tempfile.TemporaryDirectory(prefix="g7-grade-") as tmp:
        tdir = Path(tmp)
        s_path = tdir / "inspect_g7.py"
        s_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_g7.py"],
            extra_mounts={s_path: "/grade_scripts/inspect_g7.py"},
            output_dir=out_dir,
            timeout=120,
            network_none=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G7-acme-event-contract",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))

    hidden = data.get("hidden", {})

    def h_ok(key: str) -> bool:
        return bool((hidden.get(key) or {}).get("passed"))

    cand_ok = bool(data.get("cand_tests_ok"))
    contract_tests_ok = cand_ok and bool(data.get("has_contract_tests"))

    g1_gate = cand_ok and h_ok("h_valid_envelope_and_z_utc")
    g2_gate = (
        h_ok("h_valid_envelope_and_z_utc")
        and h_ok("h_missing_and_generic_idempotency_key")
        and h_ok("h_canonical_replay_and_restart")
        and h_ok("h_conflict_409")
        and h_ok("h_invalid_payload_400")
    )
    g3_gate = h_ok("h_zero_pii_audit_every_mutation")

    checks = [
        CheckOutcome(
            id="g7_envelope_v2_and_utc_z",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_valid_envelope_and_z_utc"),
            detail=(hidden.get("h_valid_envelope_and_z_utc") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g7_acme_idempotency_header_strict",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_missing_and_generic_idempotency_key"),
            detail=(hidden.get("h_missing_and_generic_idempotency_key") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g7_canonical_replay_and_409_conflict",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_canonical_replay_and_restart") and h_ok("h_conflict_409"),
            detail=f"replay={hidden.get('h_canonical_replay_and_restart')}, conflict={hidden.get('h_conflict_409')}",
        ),
        CheckOutcome(
            id="g7_invalid_payload_structured_error",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_invalid_payload_400"),
            detail=(hidden.get("h_invalid_payload_400") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g7_contract_tests_pass",
            dimension="test_tdd_quality",
            passed=contract_tests_ok,
            detail=f"cand_ok={cand_ok}, has_contract_tests={data.get('has_contract_tests')}",
        ),
        CheckOutcome(
            id="g7_zero_pii_audit_all_mutations",
            dimension="solution_performance_security",
            critical=True,
            passed=g3_gate,
            detail=(hidden.get("h_zero_pii_audit_every_mutation") or {}).get("detail", ""),
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G7-acme-event-contract",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
    )
