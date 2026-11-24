"""Hidden deterministic grader for G3-systematic-debugging."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

CONTAINER_SCRIPT = r"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace")

OUT_DIR = Path("/grade_out")


def run_pytest(cwd: str = "/workspace"):
    return subprocess.run(
        ["/opt/skilleval-py/bin/python", "-m", "pytest", "-v", "--tb=short"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def run_hidden_tests() -> dict:
    from billing_svc.batch_runner import BatchRunner
    from billing_svc.cache import DEFAULT_POLICY, TenantPolicyCache, TenantPolicyStore
    from billing_svc.currency import apply_bps, compute_tax_cents
    from billing_svc.ledger import CreditLedger
    from billing_svc.models import BatchItem, InvoiceTotalMismatchError, PricingError, WebhookPayment
    from billing_svc.pricing import generate_invoice
    from billing_svc.reconciler import reconcile_payment
    from billing_svc.tax_engine import TaxEngine
    from billing_svc.webhook import parse_batch_payload

    results = {}

    def check(name, fn):
        try:
            fn()
            results[name] = {"passed": True, "detail": "ok"}
        except Exception as exc:
            results[name] = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}

    def t_interleaved_promos():
        baseline_default = copy.deepcopy(DEFAULT_POLICY)
        cache = TenantPolicyCache()
        inv_a = generate_invoice("i1", "t-alpha", 3, promo_code="ANNUAL20", cache=cache)
        inv_b = generate_invoice("i2", "t-beta", 3, cache=cache)
        inv_c = generate_invoice("i3", "t-gamma", 3, promo_code="PARTNER10", cache=cache)
        inv_d = generate_invoice("i4", "t-delta", 3, cache=cache)
        assert inv_a.discount_cents == 6_000 and inv_a.total_cents == 25_920
        assert inv_b.discount_cents == 0 and inv_b.total_cents == 32_400
        assert inv_c.discount_cents == 3_000 and inv_c.total_cents == 29_160
        assert inv_d.discount_cents == 0 and inv_d.total_cents == 32_400
        assert DEFAULT_POLICY == baseline_default, f"DEFAULT_POLICY mutated: {DEFAULT_POLICY}"

    def t_feature_credits_isolation():
        cache = TenantPolicyCache()
        inv1 = generate_invoice("c1", "t-cred-1", 2, grant_credit_cents=2_500, cache=cache)
        inv2 = generate_invoice("c2", "t-cred-2", 2, cache=cache)
        assert inv1.credit_cents == 2_500
        assert inv2.credit_cents == 0, f"Tenant 2 leaked credit_cents={inv2.credit_cents}"

    def t_same_tenant_no_sticky_promo_or_credit():
        cache = TenantPolicyCache()
        inv1 = generate_invoice("r1", "t-repeat", 2, promo_code="ANNUAL20", grant_credit_cents=1_500, cache=cache)
        inv2 = generate_invoice("r2", "t-repeat", 2, cache=cache)
        assert inv1.discount_cents == 4_000 and inv1.credit_cents == 1_500
        assert inv2.discount_cents == 0 and inv2.credit_cents == 0, f"Sticky state leaked to inv2: {inv2}"

    def t_store_override_and_invalidate():
        overrides = {
            "vip": {"base_rate_cents": 8_000, "discounts": {"VIP": 500}, "feature_credits": [500], "tax_bps": 800}
        }
        orig = copy.deepcopy(overrides)
        store = TenantPolicyStore(overrides)
        cache = TenantPolicyCache(store)
        inv1 = generate_invoice("v1", "vip", 2, promo_code="ANNUAL20", grant_credit_cents=300, cache=cache)
        inv2 = generate_invoice("v2", "vip", 2, cache=cache)
        assert inv1.discount_cents == 3_200 and inv1.credit_cents == 800
        assert inv2.discount_cents == 800 and inv2.credit_cents == 500
        assert overrides == orig, "Caller overrides mutated"
        cache.invalidate("vip")
        inv3 = generate_invoice("v3", "vip", 2, cache=cache)
        assert inv3.total_cents == inv2.total_cents

    def t_reconciler_exact_cent():
        cache = TenantPolicyCache()
        inv = generate_invoice("rec-1", "t-rec", 2, cache=cache)
        ok_pay = WebhookPayment("p1", "rec-1", "t-rec", inv.total_cents)
        assert reconcile_payment(inv, ok_pay) == "reconciled"
        for delta in (-1, 1, 5, -100):
            bad_pay = WebhookPayment("p-bad", "rec-1", "t-rec", inv.total_cents + delta)
            try:
                reconcile_payment(inv, bad_pay)
            except InvoiceTotalMismatchError:
                continue
            raise AssertionError(f"Reconciler failed to reject delta={delta} cents")

    def t_currency_exact():
        assert apply_bps(105, 500) == 5
        assert apply_bps(110, 500) == 6
        assert apply_bps(33_333, 1500) == 5_000
        assert compute_tax_cents(10_000, 800) == 800

    def t_tax_engine_quarter_and_exempt_isolation():
        engine = TaxEngine()
        inv_ex = generate_invoice("tx-e", "t-ex", 1, country="US", quarter="2026Q1", tax_exempt=True, tax_engine=engine)
        inv_q1 = generate_invoice("tx-1", "t-q1", 1, country="US", quarter="2026Q1", tax_engine=engine)
        inv_q2 = generate_invoice("tx-2", "t-q2", 1, country="US", quarter="2026Q2", tax_engine=engine)
        inv_de = generate_invoice("tx-3", "t-de", 1, country="DE", quarter="2026Q2", tax_engine=engine)
        inv_q1_again = generate_invoice("tx-4", "t-q1b", 1, country="US", quarter="2026Q1", tax_engine=engine)
        assert inv_ex.tax_cents == 0, f"Exempt had tax={inv_ex.tax_cents}"
        assert inv_q1.tax_cents == 800, f"US Q1 poisoned by exempt: {inv_q1.tax_cents}"
        assert inv_q2.tax_cents == 825, f"US Q2 leaked Q1 rate: {inv_q2.tax_cents}"
        assert inv_de.tax_cents == 2_000, f"DE Q2 wrong tax={inv_de.tax_cents}"
        assert inv_q1_again.tax_cents == 800
        assert engine.lookups == 3, f"Expected 3 cached schedule lookups, got {engine.lookups}"

    def t_batch_runner_ledger_rollback():
        ledger = CreditLedger({"t-roll": 5_000, "t-clean": 1_000})
        runner = BatchRunner(ledger=ledger)
        res = runner.process_batch([
            BatchItem("b-bad-seats", "t-roll", seats=0, ledger_credit_cents=5_000),
            BatchItem("b-bad-pay", "t-roll", seats=1, ledger_credit_cents=2_000, payment_cents=9_999),
            BatchItem("b-clean", "t-clean", seats=1, country="US", quarter="2026Q1", ledger_credit_cents=1_000, payment_cents=9_720),
            BatchItem("b-ok-after", "t-roll", seats=1, country="US", quarter="2026Q1", ledger_credit_cents=5_000, payment_cents=5_400),
        ])
        assert res[0].status == "failed" and res[1].status == "failed"
        assert res[2].status == "reconciled", res[2]
        assert res[3].status == "reconciled", res[3]
        assert res[3].invoice is not None and res[3].invoice.credit_cents == 5_000, res[3]
        assert ledger.balance("t-roll") == 0, f"Ledger leaked balance={ledger.balance('t-roll')}"

    def t_excess_ledger_credit_refunded():
        ledger = CreditLedger({"t-cap": 5_000, "t-over": 20_000})
        runner = BatchRunner(ledger=ledger)
        res = runner.process_batch([
            BatchItem("cap-1", "t-cap", seats=1, promo_code="ANNUAL20", grant_credit_cents=6_000, ledger_credit_cents=5_000, payment_cents=0),
            BatchItem("over-1", "t-over", seats=1, ledger_credit_cents=15_000, payment_cents=0),
        ])
        assert res[0].status == "reconciled" and res[0].invoice is not None
        assert res[0].invoice.credit_cents == 8_000 and res[0].invoice.total_cents == 0
        assert ledger.balance("t-cap") == 3_000, f"Expected 3000 refund, got {ledger.balance('t-cap')}"
        assert res[1].status == "reconciled" and res[1].invoice is not None
        assert res[1].invoice.credit_cents == 10_000 and res[1].invoice.total_cents == 0
        assert ledger.balance("t-over") == 10_000, f"Expected 10000 balance, got {ledger.balance('t-over')}"

    def t_duplicate_reconciled_invoice_idempotent():
        ledger = CreditLedger({"t-idem": 10_000, "t-retry": 5_000})
        runner = BatchRunner(ledger=ledger)
        dup_item = BatchItem("idem-1", "t-idem", seats=1, ledger_credit_cents=5_000, payment_cents=5_400)
        res1 = runner.process_batch([dup_item, dup_item])
        res2 = runner.process_batch([dup_item])
        assert res1[0].status == "reconciled" and res1[1].status == "reconciled"
        assert res2[0].status == "reconciled" and res2[0].invoice == res1[0].invoice
        assert ledger.balance("t-idem") == 5_000, f"Double-debited balance={ledger.balance('t-idem')}"

        # Failed invoice_id must NOT be locked out of subsequent clean retry
        fail_first = runner.process_batch([BatchItem("retry-1", "t-retry", seats=1, ledger_credit_cents=5_000, payment_cents=999)])
        assert fail_first[0].status == "failed" and ledger.balance("t-retry") == 5_000
        ok_retry = runner.process_batch([BatchItem("retry-1", "t-retry", seats=1, ledger_credit_cents=5_000, payment_cents=5_400)])
        assert ok_retry[0].status == "reconciled" and ledger.balance("t-retry") == 0

    def t_defense_in_depth_validation():
        # Entry webhook validation + normalization
        try:
            parse_batch_payload([{"invoice_id": "w1", "tenant_id": "   ", "seats": 1}])
            raise AssertionError("parse_batch_payload accepted whitespace tenant_id")
        except (PricingError, ValueError):
            pass

        parsed = parse_batch_payload([{"invoice_id": " w2 ", "tenant_id": " t-norm ", "seats": 1, "country": " us ", "quarter": "2026q2"}])
        assert parsed[0].tenant_id == "t-norm"
        assert parsed[0].country == "US" and parsed[0].quarter == "2026Q2"

        # Inner layers enforce tenant validation even when webhook entry is bypassed
        for label, fn in [
            ("cache", lambda: TenantPolicyCache().get_policy("  ")),
            ("ledger", lambda: CreditLedger().apply_credit("", 100)),
            ("pricing", lambda: generate_invoice("p-bad", "   ", 1)),
        ]:
            try:
                fn()
            except (PricingError, ValueError):
                continue
            raise AssertionError(f"Inner layer '{label}' accepted empty/blank tenant_id")

        runner = BatchRunner()
        items = parse_batch_payload([{"invoice_id": "norm-inv", "tenant_id": " t-us ", "seats": 1, "country": " us ", "quarter": "2026q2"}])
        out = runner.process_batch(items)
        assert out[0].status == "invoiced" and out[0].invoice is not None
        assert out[0].invoice.tax_cents == 825, out[0]

    def t_cache_efficiency():
        store = TenantPolicyStore()
        cache = TenantPolicyCache(store)
        for i in range(20):
            tid = f"tenant-{i % 4}"
            generate_invoice(f"perf-{i}", tid, 2, promo_code="PARTNER10" if i % 5 == 0 else None, cache=cache)
        assert store.load_calls == 4, f"Expected 4 backing store loads, got {store.load_calls}"
        assert cache.hits >= 16, f"Expected >=16 cache hits, got {cache.hits}"

    check("h_interleaved_promos", t_interleaved_promos)
    check("h_feature_credits_isolation", t_feature_credits_isolation)
    check("h_same_tenant_no_sticky_state", t_same_tenant_no_sticky_promo_or_credit)
    check("h_store_override_and_invalidate", t_store_override_and_invalidate)
    check("h_tax_engine_quarter_and_exempt_isolation", t_tax_engine_quarter_and_exempt_isolation)
    check("h_batch_runner_ledger_rollback", t_batch_runner_ledger_rollback)
    check("h_excess_ledger_credit_refunded", t_excess_ledger_credit_refunded)
    check("h_duplicate_reconciled_invoice_idempotent", t_duplicate_reconciled_invoice_idempotent)
    check("h_defense_in_depth_validation", t_defense_in_depth_validation)
    check("h_reconciler_exact_cent", t_reconciler_exact_cent)
    check("h_currency_exact", t_currency_exact)
    check("h_cache_efficiency", t_cache_efficiency)
    return results


def main():
    diag = Path("/workspace/DIAGNOSIS.md")
    diag_text = diag.read_text(encoding="utf-8", errors="replace").strip() if diag.is_file() else ""
    cand_pass = run_pytest("/workspace")
    # Run candidate tests against unfixed starter package in an isolated temp directory
    starter_tmp = Path(tempfile.mkdtemp(prefix="starter-repro-"))
    shutil.copytree("/workspace/tests", starter_tmp / "tests")
    shutil.copytree("/starter_ref/billing_svc", starter_tmp / "billing_svc")
    cand_against_starter = run_pytest(str(starter_tmp))
    failed_lines = [
        ln for ln in cand_against_starter.stdout.splitlines()
        if ln.startswith("FAILED ")
    ]
    non_repro_failures = [
        ln for ln in failed_lines
        if "test_tenant_b_does_not_inherit_tenant_a_promo" not in ln
    ]

    hidden = run_hidden_tests()
    payload = {
        "diagnosis_exists": diag.is_file(),
        "diagnosis_len": len(diag_text),
        "cand_tests_ok": cand_pass.returncode == 0,
        "cand_tests_out": cand_pass.stdout[-800:],
        "starter_failed_count": len(failed_lines),
        "new_regression_failures_on_starter": non_repro_failures,
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
    _ = deliverables
    if not (workspace / "billing_svc" / "cache.py").is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G3-systematic-debugging",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
            checks=[
                CheckOutcome(
                    id="g3_package_present",
                    dimension="correctness_completeness",
                    critical=True,
                    passed=False,
                    detail="Missing billing_svc/cache.py",
                )
            ],
        )

    starter_pkg = task_dir / "starter" / "billing_svc"
    with tempfile.TemporaryDirectory(prefix="g3-grade-") as tmp:
        tdir = Path(tmp)
        script_path = tdir / "inspect_g3.py"
        script_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_g3.py"],
            extra_mounts={
                script_path: "/grade_scripts/inspect_g3.py",
                starter_pkg: "/starter_ref/billing_svc",
            },
            output_dir=out_dir,
            timeout=120,
            network_none=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G3-systematic-debugging",
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
    diag_ok = bool(data.get("diagnosis_exists")) and int(data.get("diagnosis_len", 0)) >= 120
    cand_ok = bool(data.get("cand_tests_ok"))
    starter_reg_n = len(data.get("new_regression_failures_on_starter") or [])
    regression_ok = starter_reg_n >= 3

    def h_ok(key: str) -> bool:
        return bool((hidden.get(key) or {}).get("passed"))

    g1_gate = cand_ok and diag_ok
    g2_gate = (
        h_ok("h_interleaved_promos")
        and h_ok("h_feature_credits_isolation")
        and h_ok("h_same_tenant_no_sticky_state")
        and h_ok("h_store_override_and_invalidate")
        and h_ok("h_tax_engine_quarter_and_exempt_isolation")
        and h_ok("h_batch_runner_ledger_rollback")
    )
    g3_gate = h_ok("h_reconciler_exact_cent") and h_ok("h_currency_exact")

    checks = [
        CheckOutcome(
            id="g3_candidate_tests_and_diagnosis",
            dimension="correctness_completeness",
            critical=True,
            passed=cand_ok and diag_ok,
            detail=f"cand_ok={cand_ok}, diagnosis_len={data.get('diagnosis_len')}",
        ),
        CheckOutcome(
            id="g3_interleaved_promo_and_default_policy",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_interleaved_promos"),
            detail=(hidden.get("h_interleaved_promos") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_feature_credits_isolation",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_feature_credits_isolation"),
            detail=(hidden.get("h_feature_credits_isolation") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_same_tenant_repeated_invoice",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_same_tenant_no_sticky_state"),
            detail=(hidden.get("h_same_tenant_no_sticky_state") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_store_override_invalidation",
            dimension="robustness_edge_cases",
            passed=h_ok("h_store_override_and_invalidate"),
            detail=(hidden.get("h_store_override_and_invalidate") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_tax_engine_quarter_and_exempt",
            dimension="correctness_completeness",
            critical=True,
            passed=h_ok("h_tax_engine_quarter_and_exempt_isolation"),
            detail=(hidden.get("h_tax_engine_quarter_and_exempt_isolation") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_batch_runner_ledger_rollback",
            dimension="robustness_edge_cases",
            critical=True,
            passed=h_ok("h_batch_runner_ledger_rollback"),
            detail=(hidden.get("h_batch_runner_ledger_rollback") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_excess_ledger_credit_refunded",
            dimension="correctness_completeness",
            passed=h_ok("h_excess_ledger_credit_refunded"),
            detail=(hidden.get("h_excess_ledger_credit_refunded") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_duplicate_invoice_idempotency",
            dimension="robustness_edge_cases",
            passed=h_ok("h_duplicate_reconciled_invoice_idempotent"),
            detail=(hidden.get("h_duplicate_reconciled_invoice_idempotent") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_defense_in_depth_validation",
            dimension="solution_performance_security",
            passed=h_ok("h_defense_in_depth_validation"),
            detail=(hidden.get("h_defense_in_depth_validation") or {}).get("detail", ""),
        ),
        CheckOutcome(
            id="g3_regression_tests_catch_unfixed_starter",
            dimension="test_tdd_quality",
            passed=regression_ok,
            score_fraction=round(min(1.0, starter_reg_n / 4.0), 4),
            detail=f"non_repro_failures_on_starter={data.get('new_regression_failures_on_starter')}",
        ),
        CheckOutcome(
            id="g3_exact_cent_reconciler_and_currency",
            dimension="solution_performance_security",
            critical=True,
            passed=g3_gate,
            detail=f"reconciler={hidden.get('h_reconciler_exact_cent')}, currency={hidden.get('h_currency_exact')}",
        ),
        CheckOutcome(
            id="g3_cache_hit_efficiency",
            dimension="solution_performance_security",
            passed=h_ok("h_cache_efficiency"),
            detail=(hidden.get("h_cache_efficiency") or {}).get("detail", ""),
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G3-systematic-debugging",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "cache_efficiency": h_ok("h_cache_efficiency"),
            "starter_regressions_caught": starter_reg_n,
        },
    )
