Build a dynamic 12-month SaaS financial and cash-flow model in Excel (`outputs/saas_financial_model.xlsx`) using the baseline parameters and schedule specification in `README.md` and `data/baseline_inputs.json`.

Requirements summary:
1. Create the exact four worksheets in order: `Inputs`, `Assumptions`, `Cash Flow 12M`, and `Summary`.
2. Place every editable parameter at the exact coordinates specified in `README.md` (`Inputs!B4:B17` and `Inputs!B21:B32`) so changing scenarios (`Base`, `Upside`, `Downside`) or inputs updates all projections automatically through live worksheet formulas.
3. Put the exact 10 annual KPI summary formulas at `Summary!B4:B13` referencing `Cash Flow 12M` and `Inputs`.
4. Include a native Excel chart on `Summary` plotting monthly Revenue vs. Ending Cash across Months 1–12.
5. Style and format the workbook cleanly for executive financial review, and keep your reproducible Python generator script at `build_model.py` in the workspace root.
