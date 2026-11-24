# Northstar Cloud — 12-Month Financial & Cash-Flow Model Spec

Build `outputs/saas_financial_model.xlsx` (and keep your generator script at `build_model.py`) from `data/baseline_inputs.json`.

## 1. Required Tabs (Exact Names & Order)

1. `Inputs`
2. `Assumptions`
3. `Cash Flow 12M`
4. `Summary`

## 2. Exact Cell Map for Scenario & Stress Testing

### `Inputs` Sheet
Place labels in Column `A`, editable values in Column `B`, and short source/unit notes in Column `C`:

| Cell | Label | Baseline Value | Notes |
|---|---|---|---|
| `B4` | Active Scenario | `"Base"` | Accepts `"Base"`, `"Upside"`, `"Downside"` |
| `B5` | Starting Active Customers | `120` | Integer count |
| `B6` | Base Monthly ARPU | `240` | USD per active customer / month |
| `B7` | Starting Cash | `180000` | USD opening cash balance |
| `B8` | Base Monthly Churn Rate | `0.035` | Decimal fraction (`3.5%`) |
| `B9` | Variable Hosting per Active Customer | `14` | USD per active customer / month |
| `B10` | Payment Processing Fee Rate | `0.029` | Fraction of monthly revenue (`2.9%`) |
| `B11` | Corporate Tax Rate | `0.21` | Applied only when monthly EBITDA > 0 (`21.0%`) |
| `B12` | Minimum Cash Reserve Threshold | `100000` | Covenant floor for `"OK"` / `"WARNING"` status |
| `B13` | Fixed Monthly Engineering Payroll | `48000` | USD / month |
| `B14` | Fixed Monthly Cloud Base | `6500` | USD / month |
| `B15` | Fixed Monthly G&A | `9000` | USD / month |
| `B16` | Support Rep Monthly Salary | `5500` | USD / rep / month |
| `B17` | Active Customers per Support Rep | `150` | Customers supported per rep |
| `B21:B32` | Base New Customers (Months 1..12) | `[18, 20, ..., 44]` | `B21`=Month 1 (Jan) ... `B32`=Month 12 (Dec) |

### `Assumptions` Sheet
- Include a documented scenario multiplier table:
  - `Base`: New Customer Mult = `1.00`, Churn Mult = `1.00`, ARPU Mult = `1.00`
  - `Upside`: New Customer Mult = `1.25`, Churn Mult = `0.85`, ARPU Mult = `1.05`
  - `Downside`: New Customer Mult = `0.70`, Churn Mult = `1.35`, ARPU Mult = `0.95`
- Derive the active multipliers dynamically from `Inputs!$B$4`, and compute effective monthly churn (`Base Monthly Churn Rate * Active Churn Mult`) and effective monthly ARPU (`Base Monthly ARPU * Active ARPU Mult`).

### `Cash Flow 12M` Sheet (Months 1–12 across Columns `B`..`M`, Annual Summary in `N`)
For each month `m = 1..12`, implement live Excel formulas matching these exact definitions:
- **Beginning Customers**: M1 = Starting Active Customers; M2..12 = prior month Ending Customers
- **New Customers**: `ROUND(Base New Customers_m * Active New Customer Mult, 0)`
- **Churned Customers**: `ROUND(Beginning Customers * Effective Churn Rate, 0)`
- **Ending Customers**: `max(0, Beginning Customers + New Customers - Churned Customers)`
- **Revenue**: `Ending Customers * Effective ARPU`
- **Variable Hosting**: `Ending Customers * Variable Hosting per Active Customer`
- **Payment Processing Fees**: `Revenue * Payment Processing Fee Rate`
- **Gross Profit**: `Revenue - Variable Hosting - Payment Processing Fees`
- **Gross Margin %**: `Gross Profit / Revenue` (or `0` when Revenue is zero)
- **Support Headcount**: integer ceiling of `Ending Customers / Active Customers per Support Rep`, minimum `1` rep (or `1` if ratio is zero)
- **Support Payroll**: `Support Headcount * Support Rep Monthly Salary`
- **Fixed Engineering Payroll / Fixed Cloud Base / Fixed G&A**: linked to `Inputs`
- **Total OpEx**: sum of Support Payroll + Fixed Engineering Payroll + Fixed Cloud Base + Fixed G&A
- **EBITDA**: `Gross Profit - Total OpEx`
- **Corporate Taxes**: `EBITDA * Corporate Tax Rate` when EBITDA > 0, else `0`
- **Net Cash Flow**: `EBITDA - Corporate Taxes`
- **Beginning Cash**: M1 = Starting Cash; M2..12 = prior month Ending Cash
- **Ending Cash**: `Beginning Cash + Net Cash Flow`

### `Summary` Sheet
Place these 10 live KPI formulas at exact coordinates `Summary!B4:B13` (labels in `A4:A13`):
- `B4`: Annual Revenue (sum of Months 1–12 Revenue)
- `B5`: Annual Gross Profit (sum of Months 1–12 Gross Profit)
- `B6`: Annual Gross Margin % (`Annual Gross Profit / Annual Revenue`, or `0` if Revenue is zero)
- `B7`: Annual EBITDA (sum of Months 1–12 EBITDA)
- `B8`: Annual Corporate Taxes (sum of Months 1–12 Corporate Taxes)
- `B9`: Annual Net Cash Flow (sum of Months 1–12 Net Cash Flow)
- `B10`: Month 12 Ending Cash
- `B11`: Minimum Monthly Ending Cash across Months 1–12
- `B12`: Month 12 Active Customers
- `B13`: Cash Reserve Status (`"OK"` if `B11 >= Inputs!$B$12`, else `"WARNING"`)

Include a clean native Excel chart on `Summary` plotting Monthly Revenue and Ending Cash across Months 1–12.
