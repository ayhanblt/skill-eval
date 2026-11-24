Implement the multi-rule B2B subscription & usage pricing engine in `pricing_engine/calculator.py` strictly following every specification rule in `SPEC.md` and `pricing_engine/models.py`.

Requirements summary:
1. Read `SPEC.md`, `pricing_engine/models.py`, `pricing_engine/calculator.py`, and `tests/test_smoke.py` thoroughly before starting.
2. Implement `calculate_invoice(...)` supporting all tier-mode, allowance, proration, seat-segment, adjustment, discount scoping/threshold/cap, cycle-capped FIFO credit, validation, and proportional tax rules while preserving all dataclass definitions in `pricing_engine/models.py`.
3. Add a thorough automated behavioral test suite under `tests/` covering boundary interactions, rounding, validation errors, and exact invariants.
4. Run `pytest` after your final edits and confirm every test passes cleanly.
