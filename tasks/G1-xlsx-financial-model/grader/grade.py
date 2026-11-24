"""Hidden deterministic grader for G1-xlsx-financial-model."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

CONTAINER_SCRIPT = r"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, "/grade_recalc")
from recalc import recalc as lo_recalc
from office.soffice import run_soffice

from openpyxl import load_workbook

WORKBOOK = Path("/workspace/outputs/saas_financial_model.xlsx")
BASELINE = Path("/workspace/data/baseline_inputs.json")
OUT_DIR = Path("/grade_out")
PREVIEWS_DIR = OUT_DIR / "_grader_previews"
SUMMARY_DIR = OUT_DIR / "_grader_summary"
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

EXCEL_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!")
FORBIDDEN_FUNCS_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(XLOOKUP|XMATCH|FILTER|UNIQUE|SORT|SORTBY|SEQUENCE|LET|LAMBDA|IFS|SWITCH|MAXIFS|MINIFS|TEXTJOIN|CONCAT)\s*\(",
    re.IGNORECASE,
)


def excel_round(val: float, digits: int = 0) -> float:
    q = Decimal("1") if digits == 0 else Decimal("1." + "0" * digits)
    return float(Decimal(str(val)).quantize(q, rounding=ROUND_HALF_UP))


def expected_model(baseline: dict, scenario: str, zero_rev: bool = False) -> dict:
    p = baseline["parameters"]
    sc = baseline["scenarios"][scenario]
    start_cust = 0 if zero_rev else p["starting_customers"]
    arpu = 0.0 if zero_rev else p["base_monthly_arpu"] * sc["arpu_mult"]
    churn = p["base_monthly_churn"] * sc["churn_mult"]
    new_mult = sc["new_cust_mult"]
    cash = float(p["starting_cash"])

    months = []
    beg_cust = start_cust
    for m in baseline["monthly_base_new_customers"]:
        new_c = excel_round(m["new_customers"] * new_mult, 0)
        churn_c = excel_round(beg_cust * churn, 0)
        end_cust = max(0.0, beg_cust + new_c - churn_c)
        rev = end_cust * arpu
        hosting = end_cust * p["variable_hosting_per_customer"]
        fees = rev * p["payment_processing_fee_rate"]
        gp = rev - hosting - fees
        gm = 0.0 if rev == 0 else gp / rev
        import math
        reps = max(1, math.ceil(end_cust / p["customers_per_support_rep"])) if p["customers_per_support_rep"] else 1
        support = reps * p["support_rep_salary"]
        opex = p["fixed_engineering_payroll"] + p["fixed_cloud_base"] + p["fixed_ga"] + support
        ebitda = gp - opex
        tax = ebitda * p["corporate_tax_rate"] if ebitda > 0 else 0.0
        ncf = ebitda - tax
        cash = cash + ncf
        months.append({
            "end_cust": end_cust,
            "revenue": rev,
            "gp": gp,
            "gm": gm,
            "opex": opex,
            "ebitda": ebitda,
            "tax": tax,
            "ncf": ncf,
            "end_cash": cash,
        })
        beg_cust = end_cust

    ann_rev = sum(x["revenue"] for x in months)
    ann_gp = sum(x["gp"] for x in months)
    ann_gm = 0.0 if ann_rev == 0 else ann_gp / ann_rev
    ann_ebitda = sum(x["ebitda"] for x in months)
    ann_tax = sum(x["tax"] for x in months)
    ann_ncf = sum(x["ncf"] for x in months)
    end_cash_12 = months[-1]["end_cash"]
    min_cash = min(x["end_cash"] for x in months)
    end_cust_12 = months[-1]["end_cust"]
    status = "OK" if min_cash >= p["minimum_cash_reserve"] else "WARNING"
    return {
        "B4": ann_rev,
        "B5": ann_gp,
        "B6": ann_gm,
        "B7": ann_ebitda,
        "B8": ann_tax,
        "B9": ann_ncf,
        "B10": end_cash_12,
        "B11": min_cash,
        "B12": end_cust_12,
        "B13": status,
        "months": months,
    }


def libreoffice_recalc(xlsx_path: Path) -> Path:
    work = Path(tempfile.mkdtemp(prefix="lo-recalc-"))
    copy_path = work / xlsx_path.name
    shutil.copyfile(xlsx_path, copy_path)
    res = lo_recalc(str(copy_path), timeout=45)
    if "error" in res:
        raise RuntimeError(f"recalc failed: {res['error']}")
    return copy_path


def scan_workbook(xlsx_path: Path) -> dict:
    wb_f = load_workbook(xlsx_path, data_only=False)
    wb_v = load_workbook(xlsx_path, data_only=True)
    formula_count = 0
    errors = []
    unsupported = []
    sample_formulas = {}
    external_links = []

    for sname in wb_f.sheetnames:
        ws_f = wb_f[sname]
        ws_v = wb_v[sname]
        for row in ws_f.iter_rows():
            for cell in row:
                val_f = cell.value
                val_v = ws_v[cell.coordinate].value
                if isinstance(val_f, str) and val_f.startswith("="):
                    formula_count += 1
                    if FORBIDDEN_FUNCS_RE.search(val_f):
                        unsupported.append(f"{sname}!{cell.coordinate}: {val_f}")
                    if "[" in val_f and "]" in val_f:
                        external_links.append(f"{sname}!{cell.coordinate}: {val_f}")
                    if sname == "Summary" and cell.coordinate in [f"B{i}" for i in range(4, 14)]:
                        sample_formulas[f"Summary!{cell.coordinate}"] = val_f
                for check_v in (val_f, val_v):
                    if isinstance(check_v, str) and any(e in check_v for e in EXCEL_ERRORS):
                        errors.append(f"{sname}!{cell.coordinate}: {check_v}")

    summary_vals = {
        f"B{i}": wb_v["Summary"][f"B{i}"].value
        for i in range(4, 14)
    } if "Summary" in wb_v.sheetnames else {}

    # Inspect styling, formats, and charts for blind Jev factual summary
    def _norm_rgb(c):
        raw = str(getattr(getattr(c.font, "color", None), "rgb", "") or "")
        return "#" + raw[-6:].upper() if len(raw) >= 6 else raw

    def _norm_fill(c):
        fl = getattr(c, "fill", None)
        if not fl or getattr(fl, "fill_type", None) in (None, "none"):
            return ""
        raw = str(getattr(getattr(fl, "fgColor", None), "rgb", "") or "")
        return "#" + raw[-6:].upper() if len(raw) >= 6 else raw

    inputs_fonts = []
    inputs_fills = []
    inputs_formats = []
    if "Inputs" in wb_f.sheetnames:
        for i in range(4, 18):
            c = wb_f["Inputs"][f"B{i}"]
            inputs_fonts.append(_norm_rgb(c))
            fl_hex = _norm_fill(c)
            if fl_hex and fl_hex != "#000000":
                inputs_fills.append(fl_hex)
            inputs_formats.append(c.number_format)

    assumptions_notes = []
    if "Assumptions" in wb_f.sheetnames:
        for row in wb_f["Assumptions"].iter_rows(min_row=1, max_row=20, min_col=1, max_col=6, values_only=True):
            for v in row:
                if isinstance(v, str) and len(v.strip()) > 12 and not v.startswith("="):
                    assumptions_notes.append(v.strip())

    summary_fonts = []
    summary_formats = []
    charts_meta = []
    if "Summary" in wb_f.sheetnames:
        ws_s = wb_f["Summary"]
        for i in range(4, 14):
            c = ws_s[f"B{i}"]
            summary_fonts.append(_norm_rgb(c))
            summary_formats.append(c.number_format)
        for ch in getattr(ws_s, "_charts", []):
            lg = getattr(ch, "legend", None)
            charts_meta.append({
                "type": type(ch).__name__,
                "roundedCorners": getattr(ch, "roundedCorners", None),
                "legend_present": lg is not None,
                "legend_overlay": getattr(lg, "overlay", None),
                "title_overlay": getattr(getattr(ch, "title", None), "overlay", None),
                "x_axis_delete": getattr(getattr(ch, "x_axis", None), "delete", None),
                "y_axis_delete": getattr(getattr(ch, "y_axis", None), "delete", None),
            })

    cf_fonts = []
    cf_formats = []
    if "Cash Flow 12M" in wb_f.sheetnames:
        ws_cf = wb_f["Cash Flow 12M"]
        for row in ws_cf.iter_rows(min_row=2, max_row=25, min_col=2, max_col=14):
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    cf_fonts.append(_norm_rgb(c))
                    cf_formats.append(c.number_format)

    return {
        "sheetnames": wb_f.sheetnames,
        "formula_count": formula_count,
        "errors": errors,
        "unsupported_functions": unsupported,
        "external_links": external_links,
        "summary_values": summary_vals,
        "sample_summary_formulas": sample_formulas,
        "assumptions_notes": assumptions_notes[:8],
        "inputs_font_colors": sorted(set(inputs_fonts)),
        "inputs_fill_colors": sorted(set(inputs_fills)),
        "inputs_number_formats": sorted(set(inputs_formats)),
        "summary_font_colors": sorted(set(summary_fonts)),
        "summary_number_formats": sorted(set(summary_formats)),
        "cashflow_font_colors": sorted(set(cf_fonts)),
        "cashflow_number_formats": sorted(set(cf_formats)),
        "chart_count": len(charts_meta),
        "charts": charts_meta,
    }


def compare_summary(actual: dict, exp: dict) -> list[str]:
    mismatches = []
    for key in [f"B{i}" for i in range(4, 14)]:
        aval = actual.get(key)
        eval_ = exp[key]
        if key == "B13":
            if str(aval or "").strip().upper() != eval_:
                mismatches.append(f"Summary!{key}: expected {eval_!r}, got {aval!r}")
            continue
        if not isinstance(aval, (int, float)):
            mismatches.append(f"Summary!{key}: expected numeric {eval_}, got {aval!r}")
            continue
        tol = 0.002 if key == "B6" else 2.0
        if abs(float(aval) - float(eval_)) > tol:
            mismatches.append(f"Summary!{key}: expected {eval_:.4f}, got {float(aval):.4f}")
    return mismatches


def main() -> None:
    report = {
        "exists": WORKBOOK.is_file(),
        "build_script_exists": Path("/workspace/build_model.py").is_file(),
    }
    if not WORKBOOK.is_file():
        (OUT_DIR / "grade_payload.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    pre_scan = scan_workbook(WORKBOOK)
    report["pre_scan"] = pre_scan

    expected_tabs = ["Inputs", "Assumptions", "Cash Flow 12M", "Summary"]
    report["tabs_ok"] = pre_scan["sheetnames"] == expected_tabs
    report["pre_cached_present"] = all(
        pre_scan["summary_values"].get(f"B{i}") is not None for i in range(4, 14)
    )

    recalced_base = libreoffice_recalc(WORKBOOK)
    base_scan = scan_workbook(recalced_base)
    report["base_scan"] = base_scan
    report["base_mismatches"] = (
        compare_summary(base_scan["summary_values"], expected_model(baseline, "Base"))
        if report["tabs_ok"]
        else ["Missing required tabs"]
    )

    # Perturbation 1: Switch active scenario to Downside
    wb_down_src = WORKBOOK.parent / "_downside_test.xlsx"
    wb_tmp = load_workbook(WORKBOOK)
    if "Inputs" in wb_tmp.sheetnames:
        wb_tmp["Inputs"]["B4"].value = "Downside"
    wb_tmp.save(wb_down_src)
    recalced_down = libreoffice_recalc(wb_down_src)
    down_scan = scan_workbook(recalced_down)
    report["downside_scan"] = down_scan
    report["downside_mismatches"] = (
        compare_summary(down_scan["summary_values"], expected_model(baseline, "Downside"))
        if report["tabs_ok"]
        else ["Missing required tabs"]
    )

    # Perturbation 2: Zero denominator trap (starting customers = 0, ARPU = 0)
    wb_zero_src = WORKBOOK.parent / "_zero_test.xlsx"
    wb_z = load_workbook(WORKBOOK)
    if "Inputs" in wb_z.sheetnames:
        wb_z["Inputs"]["B5"].value = 0
        wb_z["Inputs"]["B6"].value = 0
    wb_z.save(wb_zero_src)
    recalced_zero = libreoffice_recalc(wb_zero_src)
    zero_scan = scan_workbook(recalced_zero)
    report["zero_scan"] = zero_scan
    report["zero_mismatches"] = (
        compare_summary(zero_scan["summary_values"], expected_model(baseline, "Base", zero_rev=True))
        if report["tabs_ok"]
        else ["Missing required tabs"]
    )

    # PDF + PNG export for ### truncation check and blind visual gallery
    pdf_dir = Path(tempfile.mkdtemp(prefix="lo-pdf-"))
    run_soffice(
        [
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf_dir),
            str(recalced_base),
        ],
        capture_output=True,
        timeout=60,
        check=True,
    )
    pdf_files = list(pdf_dir.glob("*.pdf"))
    hash_trunc_pages = 0
    if pdf_files:
        txt_proc = subprocess.run(
            ["pdftotext", str(pdf_files[0]), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        hash_trunc_pages = len(re.findall(r"#{3,}", txt_proc.stdout or ""))
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "150",
                str(pdf_files[0]),
                str(PREVIEWS_DIR / "page"),
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
    preview_files = sorted(p.name for p in PREVIEWS_DIR.glob("*.png"))
    report["pdf_hash_truncations"] = hash_trunc_pages
    report["preview_files"] = preview_files

    # Factual blind inspection artifact for Jev (no pass/fail labels or gate verdicts)
    inspection = {
        "sheetnames": base_scan["sheetnames"],
        "formula_count": base_scan["formula_count"],
        "formula_errors": base_scan["errors"],
        "unsupported_functions": base_scan["unsupported_functions"],
        "sample_summary_formulas": base_scan["sample_summary_formulas"],
        "assumptions_notes": base_scan["assumptions_notes"],
        "summary_values_cached_before_recalc": pre_scan["summary_values"],
        "inputs_font_colors": base_scan["inputs_font_colors"],
        "inputs_fill_colors": base_scan["inputs_fill_colors"],
        "inputs_number_formats": base_scan["inputs_number_formats"],
        "summary_font_colors": base_scan["summary_font_colors"],
        "summary_number_formats": base_scan["summary_number_formats"],
        "cashflow_font_colors": base_scan["cashflow_font_colors"],
        "cashflow_number_formats": base_scan["cashflow_number_formats"],
        "chart_count": base_scan["chart_count"],
        "charts": base_scan["charts"],
        "pdf_hash_truncation_count": hash_trunc_pages,
    }
    (SUMMARY_DIR / "workbook_inspection.json").write_text(
        json.dumps(inspection, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "grade_payload.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = task_dir
    workbook = workspace / "outputs" / "saas_financial_model.xlsx"
    if not workbook.is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G1-xlsx-financial-model",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
            checks=[
                CheckOutcome(
                    id="g1_deliverable_exists",
                    dimension="correctness_completeness",
                    critical=True,
                    passed=False,
                    detail="Missing outputs/saas_financial_model.xlsx",
                )
            ],
        )

    recalc_scripts_dir = task_dir.parent.parent / "skills" / "xlsx" / "scripts"
    with tempfile.TemporaryDirectory(prefix="g1-grade-") as tmp:
        tdir = Path(tmp)
        script_path = tdir / "inspect_xlsx.py"
        script_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()
        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_xlsx.py"],
            extra_mounts={
                script_path: "/grade_scripts/inspect_xlsx.py",
                recalc_scripts_dir: "/grade_recalc",
            },
            output_dir=out_dir,
            timeout=180,
            network_none=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G1-xlsx-financial-model",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))

        # Copy blind summary and PNG previews into run deliverables
        deliv_summary = deliverables / "_grader_summary"
        deliv_summary.mkdir(parents=True, exist_ok=True)
        src_summary = out_dir / "_grader_summary" / "workbook_inspection.json"
        if src_summary.is_file():
            (deliv_summary / "workbook_inspection.json").write_text(
                src_summary.read_text(encoding="utf-8"), encoding="utf-8"
            )

        deliv_prev = deliverables / "_grader_previews"
        deliv_prev.mkdir(parents=True, exist_ok=True)
        visual_previews: list[str] = []
        src_prev = out_dir / "_grader_previews"
        if src_prev.is_dir():
            for png in sorted(src_prev.glob("*.png")):
                dst = deliv_prev / png.name
                dst.write_bytes(png.read_bytes())
                visual_previews.append(f"deliverables/_grader_previews/{png.name}")

    base_scan = data.get("base_scan", {})
    down_scan = data.get("downside_scan", {})
    zero_scan = data.get("zero_scan", {})

    tabs_ok = bool(data.get("tabs_ok"))
    build_script_ok = bool(data.get("build_script_exists"))
    formula_count = int(base_scan.get("formula_count", 0))
    live_formulas_ok = formula_count >= 120
    base_values_ok = len(data.get("base_mismatches") or []) == 0 and len(base_scan.get("errors") or []) == 0
    down_ok = len(data.get("downside_mismatches") or []) == 0 and len(down_scan.get("errors") or []) == 0
    zero_ok = len(data.get("zero_mismatches") or []) == 0 and len(zero_scan.get("errors") or []) == 0
    pre_cached_ok = bool(data.get("pre_cached_present"))
    chart_list = base_scan.get("charts") or []
    chart_ok = len(chart_list) >= 1
    # LibreOffice Calc strips c:roundedCorners=0 on save (reading back as None), while preserving
    # explicit legend/title overlay and axis delete flags (or rejecting True if roundedCorners is set).
    chart_hygiene_ok = chart_ok and all(
        ch.get("roundedCorners") is not True
        and ch.get("legend_present") is True
        and ch.get("legend_overlay") is False
        and ch.get("title_overlay") is False
        and ch.get("x_axis_delete") is False
        and ch.get("y_axis_delete") is False
        for ch in chart_list
    )

    def _is_yellow_fill(hex_str: str) -> bool:
        if len(hex_str) != 7 or not hex_str.startswith("#"):
            return False
        try:
            r, g, b = int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
        except ValueError:
            return False
        return r >= 240 and g >= 230 and b <= 235

    in_fonts = set(base_scan.get("inputs_font_colors") or [])
    sum_fonts = set(base_scan.get("summary_font_colors") or [])
    cf_fonts = set(base_scan.get("cashflow_font_colors") or [])
    all_fmts = (
        list(base_scan.get("inputs_number_formats") or [])
        + list(base_scan.get("summary_number_formats") or [])
        + list(base_scan.get("cashflow_number_formats") or [])
    )
    has_dash_currency = any("$" in fmt and ";" in fmt and ("-" in fmt or "\u2013" in fmt) for fmt in all_fmts)
    styling_ok = (
        "#0000FF" in in_fonts
        and any(_is_yellow_fill(h) for h in (base_scan.get("inputs_fill_colors") or []))
        and "#008000" in (sum_fonts | cf_fonts)
        and "#000000" in (sum_fonts | cf_fonts)
        and has_dash_currency
    )

    no_unsupported_ok = (
        len(base_scan.get("unsupported_functions") or []) == 0
        and len(base_scan.get("external_links") or []) == 0
    )
    no_hash_trunc_ok = int(data.get("pdf_hash_truncations", 99)) == 0
    rendered_ok = len(visual_previews) >= 1

    g1_gate = tabs_ok and build_script_ok and rendered_ok
    g2_gate = live_formulas_ok and base_values_ok and down_ok and zero_ok and pre_cached_ok
    g3_gate = no_unsupported_ok and no_hash_trunc_ok and chart_hygiene_ok

    checks = [
        CheckOutcome(
            id="g1_tabs_and_script",
            dimension="correctness_completeness",
            critical=True,
            passed=tabs_ok and build_script_ok,
            detail=f"sheets={base_scan.get('sheetnames')}, build_model.py={build_script_ok}",
        ),
        CheckOutcome(
            id="g1_live_formula_count",
            dimension="correctness_completeness",
            critical=True,
            passed=live_formulas_ok,
            detail=f"formula_count={formula_count} (min 120)",
        ),
        CheckOutcome(
            id="g1_base_kpis_exact",
            dimension="correctness_completeness",
            critical=True,
            passed=base_values_ok,
            detail="; ".join(data.get("base_mismatches") or []) or "All 10 Base KPIs matched",
        ),
        CheckOutcome(
            id="g1_scenario_downside_dynamic",
            dimension="robustness_edge_cases",
            critical=True,
            passed=down_ok,
            detail="; ".join(data.get("downside_mismatches") or []) or "Downside perturbation matched",
        ),
        CheckOutcome(
            id="g1_zero_denominator_guard",
            dimension="robustness_edge_cases",
            critical=True,
            passed=zero_ok,
            detail="; ".join(data.get("zero_mismatches") or []) or "Zero-revenue stress test clean",
        ),
        CheckOutcome(
            id="g1_pre_recalc_cached_values",
            dimension="robustness_edge_cases",
            critical=True,
            passed=pre_cached_ok,
            detail="Cached Summary values present before grader recalc"
            if pre_cached_ok
            else "Summary cached values were None (workbook was not recalculated)",
        ),
        CheckOutcome(
            id="g1_embedded_chart",
            dimension="correctness_completeness",
            passed=chart_ok,
            detail=f"chart_count={base_scan.get('chart_count', 0)}",
        ),
        CheckOutcome(
            id="g1_chart_xml_hygiene",
            dimension="code_output_maintainability",
            critical=True,
            passed=chart_hygiene_ok,
            detail=f"charts={chart_list}",
        ),
        CheckOutcome(
            id="g1_financial_styling_and_fills",
            dimension="code_output_maintainability",
            passed=styling_ok,
            detail=f"in_fonts={sorted(in_fonts)}, fills={base_scan.get('inputs_fill_colors')}, dash_usd={has_dash_currency}",
        ),
        CheckOutcome(
            id="g1_portable_formulas_no_links",
            dimension="solution_performance_security",
            critical=True,
            passed=no_unsupported_ok,
            detail=f"unsupported={base_scan.get('unsupported_functions')}, ext={base_scan.get('external_links')}",
        ),
        CheckOutcome(
            id="g1_no_pdf_hash_truncation",
            dimension="solution_performance_security",
            critical=True,
            passed=no_hash_trunc_ok,
            detail=f"pdf_hash_truncations={data.get('pdf_hash_truncations')}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G1-xlsx-financial-model",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "formula_count": formula_count,
            "chart_count": base_scan.get("chart_count", 0),
            "pdf_hash_truncations": data.get("pdf_hash_truncations", 0),
        },
        visual_previews=visual_previews,
    )
