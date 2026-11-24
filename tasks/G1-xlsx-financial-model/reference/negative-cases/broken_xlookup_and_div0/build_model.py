#!/usr/bin/env python3
"""Flawed negative case: uses bare XLOOKUP, unguarded /0 division, and skips LibreOffice recalc."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "baseline_inputs.json"
OUT_PATH = ROOT / "outputs" / "saas_financial_model.xlsx"


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    p = data["parameters"]
    wb = Workbook()
    ws_in = wb.active
    ws_in.title = "Inputs"
    ws_in["B4"] = data["active_scenario"]
    ws_in["B5"] = p["starting_customers"]
    ws_in["B6"] = p["base_monthly_arpu"]
    ws_in["B7"] = p["starting_cash"]
    ws_in["B8"] = p["base_monthly_churn"]
    ws_in["B9"] = p["variable_hosting_per_customer"]
    ws_in["B10"] = p["payment_processing_fee_rate"]
    ws_in["B11"] = p["corporate_tax_rate"]
    ws_in["B12"] = p["minimum_cash_reserve"]
    ws_in["B13"] = p["fixed_engineering_payroll"]
    ws_in["B14"] = p["fixed_cloud_base"]
    ws_in["B15"] = p["fixed_ga"]
    ws_in["B16"] = p["support_rep_salary"]
    ws_in["B17"] = p["customers_per_support_rep"]
    for idx, m in enumerate(data["monthly_base_new_customers"], start=21):
        ws_in[f"B{idx}"] = m["new_customers"]

    ws_as = wb.create_sheet("Assumptions")
    for idx, (k, sc) in enumerate(data["scenarios"].items(), start=5):
        ws_as[f"A{idx}"] = k
        ws_as[f"B{idx}"] = sc["new_cust_mult"]
        ws_as[f"C{idx}"] = sc["churn_mult"]
        ws_as[f"D{idx}"] = sc["arpu_mult"]
    # Bare XLOOKUP breaks LibreOffice!
    ws_as["B12"] = "=XLOOKUP(Inputs!$B$4,A5:A7,B5:B7)"
    ws_as["B13"] = "=XLOOKUP(Inputs!$B$4,A5:A7,C5:C7)"
    ws_as["B14"] = "=XLOOKUP(Inputs!$B$4,A5:A7,D5:D7)"

    ws_cf = wb.create_sheet("Cash Flow 12M")
    for m_idx in range(1, 13):
        col = get_column_letter(m_idx + 1)
        prev = get_column_letter(m_idx)
        ws_cf[f"{col}5"] = "=Inputs!$B$5" if m_idx == 1 else f"={prev}8"
        ws_cf[f"{col}6"] = f"=ROUND(Inputs!$B{20+m_idx}*Assumptions!$B$12,0)"
        ws_cf[f"{col}7"] = f"=ROUND({col}5*Inputs!$B$8*Assumptions!$B$13,0)"
        ws_cf[f"{col}8"] = f"=MAX(0,{col}5+{col}6-{col}7)"
        ws_cf[f"{col}9"] = f"={col}8*Inputs!$B$6*Assumptions!$B$14"
        ws_cf[f"{col}10"] = f"={col}8*Inputs!$B$9"
        ws_cf[f"{col}11"] = f"={col}9*Inputs!$B$10"
        ws_cf[f"{col}12"] = f"={col}9-{col}10-{col}11"
        # Unguarded division by zero!
        ws_cf[f"{col}13"] = f"={col}12/{col}9"
        ws_cf[f"{col}14"] = f"=MAX(1,ROUNDUP({col}8/Inputs!$B$17,0))"
        ws_cf[f"{col}15"] = f"={col}14*Inputs!$B$16"
        ws_cf[f"{col}19"] = f"={col}15+Inputs!$B$13+Inputs!$B$14+Inputs!$B$15"
        ws_cf[f"{col}20"] = f"={col}12-{col}19"
        ws_cf[f"{col}21"] = f"=IF({col}20>0,{col}20*Inputs!$B$11,0)"
        ws_cf[f"{col}22"] = f"={col}20-{col}21"
        ws_cf[f"{col}23"] = "=Inputs!$B$7" if m_idx == 1 else f"={prev}24"
        ws_cf[f"{col}24"] = f"={col}23+{col}22"

    ws_sum = wb.create_sheet("Summary")
    ws_sum["B4"] = "=SUM('Cash Flow 12M'!B9:M9)"
    ws_sum["B5"] = "=SUM('Cash Flow 12M'!B12:M12)"
    ws_sum["B6"] = "=B5/B4"  # Unguarded /0
    ws_sum["B7"] = "=SUM('Cash Flow 12M'!B20:M20)"
    ws_sum["B8"] = "=SUM('Cash Flow 12M'!B21:M21)"
    ws_sum["B9"] = "=SUM('Cash Flow 12M'!B22:M22)"
    ws_sum["B10"] = "='Cash Flow 12M'!M24"
    ws_sum["B11"] = "=MIN('Cash Flow 12M'!B24:M24)"
    ws_sum["B12"] = "='Cash Flow 12M'!M8"
    ws_sum["B13"] = "=IF(B11>=Inputs!$B$12,\"OK\",\"WARNING\")"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT_PATH)


if __name__ == "__main__":
    main()
