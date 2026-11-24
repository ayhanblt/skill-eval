#!/usr/bin/env python3
"""Flawed negative case: hardcodes calculated values instead of live Excel formulas."""

from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "baseline_inputs.json"
OUT_PATH = ROOT / "outputs" / "saas_financial_model.xlsx"


def _round(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    p = data["parameters"]
    wb = Workbook()
    ws_in = wb.active
    ws_in.title = "Inputs"
    ws_in["A4"], ws_in["B4"] = "Active Scenario", data["active_scenario"]
    ws_in["A5"], ws_in["B5"] = "Starting Customers", p["starting_customers"]
    ws_in["A6"], ws_in["B6"] = "Base Monthly ARPU", p["base_monthly_arpu"]
    ws_in["A7"], ws_in["B7"] = "Starting Cash", p["starting_cash"]
    ws_in["A8"], ws_in["B8"] = "Base Monthly Churn", p["base_monthly_churn"]
    ws_in["A9"], ws_in["B9"] = "Hosting", p["variable_hosting_per_customer"]
    ws_in["A10"], ws_in["B10"] = "Processing Fee", p["payment_processing_fee_rate"]
    ws_in["A11"], ws_in["B11"] = "Tax Rate", p["corporate_tax_rate"]
    ws_in["A12"], ws_in["B12"] = "Min Cash", p["minimum_cash_reserve"]
    ws_in["A13"], ws_in["B13"] = "Eng Payroll", p["fixed_engineering_payroll"]
    ws_in["A14"], ws_in["B14"] = "Cloud Base", p["fixed_cloud_base"]
    ws_in["A15"], ws_in["B15"] = "GA", p["fixed_ga"]
    ws_in["A16"], ws_in["B16"] = "Support Salary", p["support_rep_salary"]
    ws_in["A17"], ws_in["B17"] = "Cust per Rep", p["customers_per_support_rep"]
    for idx, m in enumerate(data["monthly_base_new_customers"], start=21):
        ws_in[f"A{idx}"], ws_in[f"B{idx}"] = m["label"], m["new_customers"]

    wb.create_sheet("Assumptions")
    ws_cf = wb.create_sheet("Cash Flow 12M")
    ws_sum = wb.create_sheet("Summary")

    # Compute statically in Python and paste raw literals (no Excel formulas!)
    cust = p["starting_customers"]
    cash = float(p["starting_cash"])
    tot_rev = tot_gp = tot_ebitda = tot_tax = tot_ncf = 0.0
    min_cash = cash
    for col_i, m in enumerate(data["monthly_base_new_customers"], start=2):
        new_c = _round(m["new_customers"])
        ch_c = _round(cust * p["base_monthly_churn"])
        cust = max(0, cust + new_c - ch_c)
        rev = cust * p["base_monthly_arpu"]
        gp = rev - cust * p["variable_hosting_per_customer"] - rev * p["payment_processing_fee_rate"]
        reps = max(1, math.ceil(cust / p["customers_per_support_rep"]))
        opex = p["fixed_engineering_payroll"] + p["fixed_cloud_base"] + p["fixed_ga"] + reps * p["support_rep_salary"]
        ebitda = gp - opex
        tax = ebitda * p["corporate_tax_rate"] if ebitda > 0 else 0.0
        ncf = ebitda - tax
        cash += ncf
        min_cash = min(min_cash, cash)
        tot_rev += rev
        tot_gp += gp
        tot_ebitda += ebitda
        tot_tax += tax
        tot_ncf += ncf
        ws_cf.cell(row=5, column=col_i, value=rev)
        ws_cf.cell(row=6, column=col_i, value=cash)

    vals = [
        tot_rev, tot_gp, tot_gp / tot_rev, tot_ebitda, tot_tax,
        tot_ncf, cash, min_cash, cust, "OK" if min_cash >= p["minimum_cash_reserve"] else "WARNING",
    ]
    for r, v in enumerate(vals, start=4):
        ws_sum[f"B{r}"] = v

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT_PATH)


if __name__ == "__main__":
    main()
