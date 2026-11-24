Incident #4812 (Production Multi-Tenant Billing Service):
Customers and finance telemetry are reporting batch reconciliation failures, cross-quarter tax mismatches, and prepaid credit balance drift across billing workers (`tests/test_bug_repro.py` reproduces one symptom, and `incidents/incident_4812.log` captures the production incident trail).

Your task:
1. Investigate `incidents/incident_4812.log`, `billing_svc/`, and `tests/` thoroughly before making any edits.
2. Identify and fix every root defect across the service while preserving all public interfaces and cache hit behavior.
3. Add comprehensive regression tests under `tests/` covering all uncovered defect paths and edge cases.
4. Document your root-cause investigation, rejected hypotheses, and multi-layer fixes in `DIAGNOSIS.md` in the workspace root.
5. Run the full test suite (`pytest`) and confirm every test passes cleanly.
