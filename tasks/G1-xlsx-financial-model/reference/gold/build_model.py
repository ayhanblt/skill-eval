#!/usr/bin/env python3
"""Build and style Northstar Cloud 12-Month Financial & Cash-Flow Model."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "baseline_inputs.json"
OUT_PATH = ROOT / "outputs" / "saas_financial_model.xlsx"

FONT_NAME = "Arial"
BLUE_INPUT = Font(name=FONT_NAME, size=10, color="0000FF")
BLACK_FORMULA = Font(name=FONT_NAME, size=10, color="000000")
BLACK_BOLD = Font(name=FONT_NAME, size=10, bold=True, color="000000")
GREEN_LINK = Font(name=FONT_NAME, size=10, color="008000")
GREEN_BOLD = Font(name=FONT_NAME, size=10, bold=True, color="008000")
HEADER_FONT = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
TITLE_FONT = Font(name=FONT_NAME, size=13, bold=True, color="0F2C3F")
NOTE_FONT = Font(name=FONT_NAME, size=9, italic=True, color="475569")

HEADER_FILL = PatternFill("solid", fgColor="0F2C3F")
SUBHEADER_FILL = PatternFill("solid", fgColor="E2E8F0")
INPUT_FILL = PatternFill("solid", fgColor="FFFDE7")
TOTAL_FILL = PatternFill("solid", fgColor="F1F5F9")

THIN_SIDE = Side(style="thin", color="CBD5E1")
DOUBLE_BOTTOM = Side(style="double", color="0F2C3F")
TOP_THIN = Side(style="thin", color="0F2C3F")
GRID_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
TOTAL_BORDER = Border(top=TOP_THIN, bottom=DOUBLE_BOTTOM)

FMT_USD = "$#,##0;($#,##0);\"-\""
FMT_PCT = "0.0%"
FMT_INT = "#,##0"
FMT_MULT = "0.00\"x\""


def build_workbook() -> Path:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    p = data["parameters"]
    wb = Workbook()

    # ------------------------------------------------------------------
    # 1. Inputs tab
    # ------------------------------------------------------------------
    ws_in = wb.active
    ws_in.title = "Inputs"
    ws_in.views.sheetView[0].showGridLines = True

    ws_in["A1"] = f"{data['company']} — Model Inputs & Scenario Controls ({data['fiscal_year']})"
    ws_in["A1"].font = TITLE_FONT
    ws_in["A2"] = "Legend: Blue text with shaded fill = editable assumption cells; Green = cross-sheet link; Black = same-sheet formula."
    ws_in["A2"].font = NOTE_FONT

    for col, title in [("A", "Parameter"), ("B", "Value"), ("C", "Unit / Source Note")]:
        c = ws_in[f"{col}3"]
        c.value = title
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="left" if col != "B" else "right", vertical="center")

    input_rows = [
        (4, "Active Scenario", data["active_scenario"], "@", "Select Base, Upside, or Downside"),
        (5, "Starting Active Customers", p["starting_customers"], FMT_INT, "Customers at Jan 1 (baseline_inputs.json)"),
        (6, "Base Monthly ARPU", p["base_monthly_arpu"], FMT_USD, "USD per active customer per month"),
        (7, "Starting Cash", p["starting_cash"], FMT_USD, "Opening cash balance on Jan 1"),
        (8, "Base Monthly Churn Rate", p["base_monthly_churn"], FMT_PCT, "Monthly logo churn fraction"),
        (9, "Variable Hosting per Active Customer", p["variable_hosting_per_customer"], FMT_USD, "Monthly cloud COGS per active customer"),
        (10, "Payment Processing Fee Rate", p["payment_processing_fee_rate"], FMT_PCT, "Gateway fee % of monthly revenue"),
        (11, "Corporate Tax Rate", p["corporate_tax_rate"], FMT_PCT, "Applied only when monthly EBITDA > 0"),
        (12, "Minimum Cash Reserve Threshold", p["minimum_cash_reserve"], FMT_USD, "Covenant minimum cash floor"),
        (13, "Fixed Monthly Engineering Payroll", p["fixed_engineering_payroll"], FMT_USD, "Committed engineering payroll / month"),
        (14, "Fixed Monthly Cloud Base", p["fixed_cloud_base"], FMT_USD, "Baseline core platform cloud spend / month"),
        (15, "Fixed Monthly G&A", p["fixed_ga"], FMT_USD, "General & administrative overhead / month"),
        (16, "Support Rep Monthly Salary", p["support_rep_salary"], FMT_USD, "Fully loaded salary per support rep / month"),
        (17, "Active Customers per Support Rep", p["customers_per_support_rep"], FMT_INT, "Capacity ratio (min 1 rep required)"),
    ]
    for r, label, val, fmt, note in input_rows:
        ws_in[f"A{r}"] = label
        ws_in[f"A{r}"].font = BLACK_FORMULA
        ws_in[f"A{r}"].border = GRID_BORDER
        cell = ws_in[f"B{r}"]
        cell.value = val
        cell.font = BLUE_INPUT
        cell.fill = INPUT_FILL
        cell.number_format = fmt
        cell.border = GRID_BORDER
        cell.alignment = Alignment(horizontal="center" if r == 4 else "right")
        ws_in[f"C{r}"] = note
        ws_in[f"C{r}"].font = NOTE_FONT
        ws_in[f"C{r}"].border = GRID_BORDER

    ws_in["A19"] = "Monthly Base New Customer Additions"
    ws_in["A19"].font = BLACK_BOLD
    for col, title in [("A", "Month"), ("B", "Base New Customers"), ("C", "Source")]:
        c = ws_in[f"{col}20"]
        c.value = title
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    for idx, m in enumerate(data["monthly_base_new_customers"], start=21):
        ws_in[f"A{idx}"] = m["label"]
        ws_in[f"A{idx}"].font = BLACK_FORMULA
        ws_in[f"A{idx}"].border = GRID_BORDER
        c = ws_in[f"B{idx}"]
        c.value = m["new_customers"]
        c.font = BLUE_INPUT
        c.fill = INPUT_FILL
        c.number_format = FMT_INT
        c.border = GRID_BORDER
        ws_in[f"C{idx}"] = "baseline_inputs.json sales plan"
        ws_in[f"C{idx}"].font = NOTE_FONT
        ws_in[f"C{idx}"].border = GRID_BORDER

    # ------------------------------------------------------------------
    # 2. Assumptions tab
    # ------------------------------------------------------------------
    ws_as = wb.create_sheet("Assumptions")
    ws_as["A1"] = "Scenario Multipliers & Derived Operating Drivers"
    ws_as["A1"].font = TITLE_FONT
    ws_as["A2"] = "Source: Executive operating scenarios defined in data/baseline_inputs.json"
    ws_as["A2"].font = NOTE_FONT

    headers = ["Scenario", "New Customer Mult", "Churn Mult", "ARPU Mult", "Rationale"]
    for ci, h in enumerate(headers, start=1):
        c = ws_as.cell(row=4, column=ci, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL

    scen_order = [
        ("Base", "Baseline operating plan"),
        ("Upside", "Faster conversion + lower logo churn + expansion"),
        ("Downside", "Macro slowdown + elevated churn + discounting"),
    ]
    for offset, (sname, desc) in enumerate(scen_order, start=5):
        sc = data["scenarios"][sname]
        ws_as.cell(row=offset, column=1, value=sname).font = BLUE_INPUT
        for col_i, val in [(2, sc["new_cust_mult"]), (3, sc["churn_mult"]), (4, sc["arpu_mult"])]:
            c = ws_as.cell(row=offset, column=col_i, value=val)
            c.font = BLUE_INPUT
            c.fill = INPUT_FILL
            c.number_format = FMT_MULT
            c.border = GRID_BORDER
        ws_as.cell(row=offset, column=5, value=desc).font = NOTE_FONT

    ws_as["A9"] = "Active Scenario Resolution"
    ws_as["A9"].font = BLACK_BOLD
    for ci, h in enumerate(["Driver", "Formula Value", "Description"], start=1):
        c = ws_as.cell(row=10, column=ci, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL

    active_rows = [
        (11, "Selected Scenario", "=Inputs!$B$4", "@", GREEN_LINK, "Cross-sheet link to Inputs!B4"),
        (12, "Active New Customer Multiplier", "=INDEX($B$5:$B$7,MATCH($B$11,$A$5:$A$7,0))", FMT_MULT, BLACK_FORMULA, "Lookup via INDEX/MATCH"),
        (13, "Active Churn Multiplier", "=INDEX($C$5:$C$7,MATCH($B$11,$A$5:$A$7,0))", FMT_MULT, BLACK_FORMULA, "Lookup via INDEX/MATCH"),
        (14, "Active ARPU Multiplier", "=INDEX($D$5:$D$7,MATCH($B$11,$A$5:$A$7,0))", FMT_MULT, BLACK_FORMULA, "Lookup via INDEX/MATCH"),
        (15, "Effective Monthly Churn Rate", "=Inputs!$B$8*B13", FMT_PCT, GREEN_LINK, "Base churn scaled by active scenario"),
        (16, "Effective Monthly ARPU", "=Inputs!$B$6*B14", FMT_USD, GREEN_LINK, "Base ARPU scaled by active scenario"),
    ]
    for r, label, formula, fmt, font, note in active_rows:
        ws_as[f"A{r}"] = label
        ws_as[f"A{r}"].font = BLACK_FORMULA
        ws_as[f"A{r}"].border = GRID_BORDER
        c = ws_as[f"B{r}"]
        c.value = formula
        c.font = font
        c.number_format = fmt
        c.border = GRID_BORDER
        ws_as[f"C{r}"] = note
        ws_as[f"C{r}"].font = NOTE_FONT
        ws_as[f"C{r}"].border = GRID_BORDER

    # ------------------------------------------------------------------
    # 3. Cash Flow 12M tab
    # ------------------------------------------------------------------
    ws_cf = wb.create_sheet("Cash Flow 12M")
    ws_cf["A1"] = "12-Month Customer Cohort, P&L & Cash Flow Schedule"
    ws_cf["A1"].font = TITLE_FONT
    ws_cf["A2"] = "All figures in USD unless marked as customers, headcount, or %."
    ws_cf["A2"].font = NOTE_FONT

    ws_cf["A4"] = "Line Item"
    ws_cf["A4"].font = HEADER_FONT
    ws_cf["A4"].fill = HEADER_FILL
    for idx, m in enumerate(data["monthly_base_new_customers"], start=2):
        c = ws_cf.cell(row=4, column=idx, value=m["label"])
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="right")
    c_tot = ws_cf.cell(row=4, column=14, value="FY 2026 Total / End")
    c_tot.font = HEADER_FONT
    c_tot.fill = HEADER_FILL
    c_tot.alignment = Alignment(horizontal="right")

    row_specs = [
        (5, "Beginning Customers", FMT_INT, "flow_start"),
        (6, "New Customers", FMT_INT, "sum"),
        (7, "Churned Customers", FMT_INT, "sum"),
        (8, "Ending Active Customers", FMT_INT, "end"),
        (9, "Monthly Revenue", FMT_USD, "sum"),
        (10, "Variable Hosting Cost", FMT_USD, "sum"),
        (11, "Payment Processing Fees", FMT_USD, "sum"),
        (12, "Gross Profit", FMT_USD, "sum"),
        (13, "Gross Margin %", FMT_PCT, "gm"),
        (14, "Support Headcount", FMT_INT, "end"),
        (15, "Support Payroll", FMT_USD, "sum"),
        (16, "Fixed Engineering Payroll", FMT_USD, "sum"),
        (17, "Fixed Cloud Base", FMT_USD, "sum"),
        (18, "Fixed G&A", FMT_USD, "sum"),
        (19, "Total OpEx", FMT_USD, "sum"),
        (20, "EBITDA", FMT_USD, "sum"),
        (21, "Corporate Taxes", FMT_USD, "sum"),
        (22, "Net Cash Flow", FMT_USD, "sum"),
        (23, "Beginning Cash", FMT_USD, "flow_start"),
        (24, "Ending Cash", FMT_USD, "end"),
    ]

    bold_rows = {8, 9, 12, 19, 20, 22, 24}
    for r, label, _, _ in row_specs:
        c = ws_cf[f"A{r}"]
        c.value = label
        c.font = BLACK_BOLD if r in bold_rows else BLACK_FORMULA
        if r in bold_rows:
            c.fill = TOTAL_FILL
        c.border = GRID_BORDER

    for m_idx in range(1, 13):
        col_i = m_idx + 1
        col = get_column_letter(col_i)
        prev_col = get_column_letter(col_i - 1)
        input_new_row = 20 + m_idx

        formulas = {
            5: ("=Inputs!$B$5" if m_idx == 1 else f"={prev_col}8", GREEN_LINK if m_idx == 1 else BLACK_FORMULA),
            6: (f"=ROUND(Inputs!$B{input_new_row}*Assumptions!$B$12,0)", GREEN_LINK),
            7: (f"=ROUND({col}5*Assumptions!$B$15,0)", GREEN_LINK),
            8: (f"=MAX(0,{col}5+{col}6-{col}7)", BLACK_BOLD),
            9: (f"={col}8*Assumptions!$B$16", GREEN_LINK),
            10: (f"={col}8*Inputs!$B$9", GREEN_LINK),
            11: (f"={col}9*Inputs!$B$10", GREEN_LINK),
            12: (f"={col}9-{col}10-{col}11", BLACK_BOLD),
            13: (f"=IF({col}9=0,0,{col}12/{col}9)", BLACK_FORMULA),
            14: (f"=IF(Inputs!$B$17=0,1,MAX(1,ROUNDUP({col}8/Inputs!$B$17,0)))", GREEN_LINK),
            15: (f"={col}14*Inputs!$B$16", GREEN_LINK),
            16: ("=Inputs!$B$13", GREEN_LINK),
            17: ("=Inputs!$B$14", GREEN_LINK),
            18: ("=Inputs!$B$15", GREEN_LINK),
            19: (f"=SUM({col}15:{col}18)", BLACK_BOLD),
            20: (f"={col}12-{col}19", BLACK_BOLD),
            21: (f"=IF({col}20>0,{col}20*Inputs!$B$11,0)", GREEN_LINK),
            22: (f"={col}20-{col}21", BLACK_BOLD),
            23: ("=Inputs!$B$7" if m_idx == 1 else f"={prev_col}24", GREEN_LINK if m_idx == 1 else BLACK_FORMULA),
            24: (f"={col}23+{col}22", BLACK_BOLD),
        }

        for r, _, fmt, _ in row_specs:
            f_str, font = formulas[r]
            cell = ws_cf[f"{col}{r}"]
            cell.value = f_str
            cell.font = font
            cell.number_format = fmt
            if r in bold_rows:
                cell.fill = TOTAL_FILL
            cell.border = TOTAL_BORDER if r in (12, 20, 24) else GRID_BORDER

    for r, _, fmt, agg in row_specs:
        c = ws_cf[f"N{r}"]
        if agg == "sum":
            c.value = f"=SUM(B{r}:M{r})"
        elif agg == "end":
            c.value = f"=M{r}"
        elif agg == "flow_start":
            c.value = f"=B{r}"
        elif agg == "gm":
            c.value = "=IF(N9=0,0,N12/N9)"
        c.font = BLACK_BOLD
        c.number_format = fmt
        c.fill = TOTAL_FILL
        c.border = TOTAL_BORDER if r in (12, 20, 24) else GRID_BORDER

    # ------------------------------------------------------------------
    # 4. Summary tab
    # ------------------------------------------------------------------
    ws_sum = wb.create_sheet("Summary")
    ws_sum["A1"] = f"{data['company']} — Executive Financial Summary ({data['fiscal_year']})"
    ws_sum["A1"].font = TITLE_FONT
    ws_sum["A2"] = "Scenario-linked annual KPIs and 12-month liquidity trajectory."
    ws_sum["A2"].font = NOTE_FONT

    for col, title in [("A", "Key Performance Indicator"), ("B", "FY 2026 Value"), ("C", "Active Scenario")]:
        c = ws_sum[f"{col}3"]
        c.value = title
        c.font = HEADER_FONT
        c.fill = HEADER_FILL

    summary_kpis = [
        (4, "Annual Revenue", "='Cash Flow 12M'!N9", FMT_USD, GREEN_BOLD),
        (5, "Annual Gross Profit", "='Cash Flow 12M'!N12", FMT_USD, GREEN_BOLD),
        (6, "Annual Gross Margin %", "=IF(B4=0,0,B5/B4)", FMT_PCT, BLACK_BOLD),
        (7, "Annual EBITDA", "='Cash Flow 12M'!N20", FMT_USD, GREEN_BOLD),
        (8, "Annual Corporate Taxes", "='Cash Flow 12M'!N21", FMT_USD, GREEN_LINK),
        (9, "Annual Net Cash Flow", "='Cash Flow 12M'!N22", FMT_USD, GREEN_BOLD),
        (10, "Ending Cash (Month 12)", "='Cash Flow 12M'!M24", FMT_USD, GREEN_BOLD),
        (11, "Minimum Monthly Ending Cash", "=MIN('Cash Flow 12M'!B24:M24)", FMT_USD, GREEN_LINK),
        (12, "Ending Active Customers (Month 12)", "='Cash Flow 12M'!M8", FMT_INT, GREEN_BOLD),
        (13, "Cash Reserve Covenant Status", "=IF(B11>=Inputs!$B$12,\"OK\",\"WARNING\")", "@", GREEN_BOLD),
    ]
    for r, label, formula, fmt, font in summary_kpis:
        ws_sum[f"A{r}"] = label
        ws_sum[f"A{r}"].font = BLACK_BOLD if r in (4, 5, 7, 10, 13) else BLACK_FORMULA
        ws_sum[f"A{r}"].border = GRID_BORDER
        c = ws_sum[f"B{r}"]
        c.value = formula
        c.font = font
        c.number_format = fmt
        c.border = GRID_BORDER
        c.alignment = Alignment(horizontal="center" if r == 13 else "right")
        sc_cell = ws_sum[f"C{r}"]
        sc_cell.value = "=Inputs!$B$4"
        sc_cell.font = GREEN_LINK
        sc_cell.alignment = Alignment(horizontal="center")
        sc_cell.border = GRID_BORDER

    # Compact monthly chart mirror block in Summary rows 16-28 for native openpyxl chart
    ws_sum["A16"] = "Month"
    ws_sum["B16"] = "Monthly Revenue"
    ws_sum["C16"] = "Ending Cash"
    for col in ("A", "B", "C"):
        ws_sum[f"{col}16"].font = HEADER_FONT
        ws_sum[f"{col}16"].fill = HEADER_FILL
    for idx in range(1, 13):
        r = 16 + idx
        col_cf = get_column_letter(idx + 1)
        ws_sum[f"A{r}"] = f"='Cash Flow 12M'!{col_cf}4"
        ws_sum[f"A{r}"].font = GREEN_LINK
        ws_sum[f"B{r}"] = f"='Cash Flow 12M'!{col_cf}9"
        ws_sum[f"B{r}"].font = GREEN_LINK
        ws_sum[f"B{r}"].number_format = FMT_USD
        ws_sum[f"C{r}"] = f"='Cash Flow 12M'!{col_cf}24"
        ws_sum[f"C{r}"].font = GREEN_LINK
        ws_sum[f"C{r}"].number_format = FMT_USD

    chart = LineChart()
    chart.title = "Monthly Revenue & Ending Cash Trajectory"
    chart.style = 10
    chart.width = 18
    chart.height = 10
    chart.roundedCorners = False
    chart.title.overlay = False
    chart.legend.overlay = False
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.title = "USD"
    chart.x_axis.title = "Month"
    data_ref = Reference(ws_sum, min_col=2, min_row=16, max_col=3, max_row=28)
    cats_ref = Reference(ws_sum, min_col=1, min_row=17, max_row=28)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    ws_sum.add_chart(chart, "E4")

    # Column widths & landscape page setup so zero ### truncation occurs on PDF/PNG export
    ws_in.column_dimensions["A"].width = 36
    ws_in.column_dimensions["B"].width = 20
    ws_in.column_dimensions["C"].width = 48

    ws_as.column_dimensions["A"].width = 34
    ws_as.column_dimensions["B"].width = 22
    ws_as.column_dimensions["C"].width = 18
    ws_as.column_dimensions["D"].width = 18
    ws_as.column_dimensions["E"].width = 48

    ws_cf.column_dimensions["A"].width = 30
    for ci in range(2, 15):
        ws_cf.column_dimensions[get_column_letter(ci)].width = 15

    ws_sum.column_dimensions["A"].width = 34
    ws_sum.column_dimensions["B"].width = 20
    ws_sum.column_dimensions["C"].width = 18

    for ws in wb.worksheets:
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT_PATH)
    return OUT_PATH


if __name__ == "__main__":
    print("Wrote", build_workbook())
