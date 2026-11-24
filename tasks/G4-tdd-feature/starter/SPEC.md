# Acme B2B Pricing Engine Specification (`calculate_invoice`)

Implement `calculate_invoice(contract: Contract, usage: list[UsageRecord], *, as_of: date) -> InvoiceQuote` in `pricing_engine/calculator.py`.

## Business Rules & Exact Semantics

1. **Exact Monetary Arithmetic & Immutability**:
   - Perform all monetary, proration, percentage, and tax computations strictly using `decimal.Decimal` (never `float`).
   - Round every computed monetary line item, intermediate subtotal/discount/credit allocation, and final summary field to `0.01` using `ROUND_HALF_UP`.
   - The function must be strictly pure: never mutate `contract`, `usage`, or any nested dataclass/collection passed by the caller.

2. **Strict Input Validation (`PricingValidationError`)**:
   Raise `PricingValidationError` immediately if any of the following invariants is violated:
   - `billing_period_days` is not positive, or `proration_days` is outside `[1, billing_period_days]`.
   - `monthly_minimum` or `tax_rate_pct` is negative.
   - `credit_cap_pct` is below `0` or above `100`.
   - Any `SeatSegment` has negative `seats`, negative `monthly_seat_price`, non-positive `active_days`, or total `active_days` across segments exceeds `billing_period_days`.
   - Any `Adjustment` has an empty or whitespace-only `code`.
   - Any catalog SKU entry has empty `tiers`, negative `included_units`, an unrecognized `tier_mode` (must be `"GRADUATED"` or `"VOLUME"`), any tier with negative `unit_price`, non-positive `up_to`, `up_to=None` before the final tier, or non-strictly-increasing `up_to` thresholds.
   - Any `DiscountRule` has negative `value`, negative `min_subtotal`, negative `max_discount_amount` (when set), percentage `value` over `100`, or `starts_on > ends_on` when both bounds exist.
   - Any `PrepaidCredit` has negative `amount`.
   - Any `UsageRecord` has negative `quantity` or references an SKU absent from `contract.catalog`.

3. **Usage Aggregation, Included Allowance & Tier Pricing**:
   - Aggregate total usage quantity per SKU across all records and emit one line item per SKU present in `usage`, sorted alphabetically by SKU name.
   - Deduct `included_units` from each SKU's aggregated quantity before pricing; billable quantity is zero if aggregated usage does not exceed `included_units` (never negative). Even when billable units equal zero, still emit the SKU line item with `quantity = aggregated_quantity` and `amount = 0.00`.
   - In `"GRADUATED"` tier mode, price billable units progressively through each bracket (`(prev_up_to, tier.up_to]`, starting from `0`), then round the summed cost to cents.
   - In `"VOLUME"` tier mode, locate the single tier covering total billable quantity (first tier where `up_to is None` or `billable_qty <= tier.up_to`) and charge ALL billable units at that tier's `unit_price`, then round to cents.
   - In either mode, if positive billable units exceed the highest bounded tier and no unbounded catch-all tier (`up_to=None`) exists, raise `PricingValidationError`.

4. **Mid-Cycle Seat Proration**:
   - For each entry in `contract.seat_segments` (1-based index `i`), calculate `seats * monthly_seat_price * active_days / billing_period_days`, rounded individually to cents, and append a line item with SKU `SEAT_PRORATION_{i}`, quantity `seats`, and that segment's `taxable` flag. Do not pool unrounded segment amounts prior to rounding.
   - `usage_subtotal` equals the rounded sum of all usage line items and seat proration line items.

5. **Adjustments & Prorated Monthly Minimum Commitment**:
   - Append each adjustment as line item `ADJ_{code}` (`quantity=1`, rounded `amount`, and `adj.taxable`; adjustments may be positive surcharges or negative credit notes).
   - Incorporate adjustments BEFORE evaluating the minimum commitment: `pre_min_subtotal` equals `max(0.00, usage_subtotal + sum_of_rounded_adjustments)`.
   - Compute `prorated_min = monthly_minimum * proration_days / billing_period_days` (rounded to cents).
   - If `pre_min_subtotal < prorated_min`, append a taxable line item `MINIMUM_COMMIT_TRUE_UP` (`quantity=1`) for `prorated_min - pre_min_subtotal` and record that as `minimum_true_up`; otherwise `minimum_true_up` is `0.00`.
   - `gross_subtotal` is `max(0.00, pre_min_subtotal + minimum_true_up)`.

6. **Eligible, Scoped, Threshold & Capped Discounts**:
   - A discount rule is eligible on `as_of` if `as_of` falls inclusively within `[starts_on, ends_on]` (unbounded when `None`) AND `gross_subtotal >= min_subtotal`.
   - Discount base: when `target_sku` is `None`, the rule applies globally; when `target_sku` is provided, its eligible base is the sum of matching SKU line items clamped between `0.00` and `gross_subtotal`.
   - Savings calculation: `"FIXED"` gives `min(base, rounded(value))`; `"PCT"` gives `rounded(base * value / 100)`, capped at `rounded(max_discount_amount)` when `max_discount_amount` is provided, and never exceeding `base`.
   - **Non-stackable rules** (`stackable=False`): choose at most one eligible rule yielding the largest savings (breaking ties by lexicographically smallest `code`), record its `code` in `non_stackable_discount_code`, and subtract its savings from `gross_subtotal` (floored at `0.00`) to obtain `after_non_stackable`.
   - **Stackable rules** (`stackable=True`), applied after the non-stackable rule:
     1. Combine all eligible unscoped (`target_sku=None`) stackable `"PCT"` rules that do NOT have `max_discount_amount` by summing their percentages (capped at `100%`) and discounting `after_non_stackable` once (rounded, floored at `0.00`).
     2. Apply any eligible unscoped stackable `"PCT"` rules that DO have `max_discount_amount` sequentially in ascending `code` order against the remaining subtotal (capping each savings at `max_discount_amount`, flooring at `0.00`).
     3. Apply any eligible SKU-scoped (`target_sku != None`) stackable `"PCT"` rules sequentially in ascending `code` order against `min(remaining_subtotal, sku_base)` (respecting `max_discount_amount` if set).
     4. Subtract all eligible stackable `"FIXED"` rules (unscoped by their rounded `value`; scoped capped at `sku_base`), flooring `post_discount_subtotal` at `0.00`.
   - `discount_total` is `gross_subtotal - post_discount_subtotal`.

7. **Cycle-Capped FIFO Pre-Paid Credits**:
   - Retain credits with `amount > 0` and `expires_on >= as_of` (credits expiring today remain valid; expired credits `< as_of` are ignored and excluded from `remaining_credits`).
   - Sort unexpired credits in FIFO order by `(expires_on, credit_id)` ascending.
   - Maximum credit consumable in this cycle is capped at `rounded(post_discount_subtotal * credit_cap_pct / 100)`.
   - Consume unexpired credits in FIFO order up to that cycle limit, recording total `credits_applied` and returning any partially or fully unconsumed unexpired credits (`amount > 0`) as `remaining_credits` in the same FIFO order.

8. **Proportional Jurisdiction Tax & Final Total**:
   - Sum line-item `amount` values across all line items with `taxable=True` (including both positive and negative taxable adjustments), and clamp to `[0.00, gross_subtotal]` as `raw_taxable_gross`.
   - `post_credit_subtotal` is `post_discount_subtotal - credits_applied`.
   - If `tax_exempt` is true, or `gross_subtotal == 0`, or `raw_taxable_gross == 0`, or `tax_rate_pct == 0`, both `net_taxable_subtotal` and `tax_amount` are `0.00`.
   - Otherwise set `net_taxable_subtotal = rounded(post_credit_subtotal * raw_taxable_gross / gross_subtotal)` and `tax_amount = rounded(net_taxable_subtotal * tax_rate_pct / 100)`.
   - `total_due` is `post_credit_subtotal + tax_amount`.
