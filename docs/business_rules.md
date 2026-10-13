# Business rules and KPI definitions

One set of definitions, implemented four times and checked against each other:

| Layer | Where | Checked by |
|---|---|---|
| Python | `python/kpi_definitions.py` | `tests/test_data_quality.py` |
| SQL (MySQL 8.0) | `sql/03_transformations.sql`, `sql/04_business_analysis.sql` | `python/verify_sql_against_python.py` (run on SQLite, see limits in the README) |
| DAX | `powerbi/DAX_Measures.md` | **not executed**; check against `docs/powerbi_reference_values.md` |
| Streamlit | `streamlit_app/app.py` (imports the Python module) | `tests/test_streamlit_app.py` |

If a rule changes, change it in all four places and re-run the tests. All data is **synthetic**.

## Order lifecycle

| Term | Definition | Counts towards revenue, profit, orders, customers, margin, AOV? |
|---|---|---|
| **Placed** | the order exists in `orders` (any status) | no, but used for cancellation and return rates |
| **Completed** | `order_status = 'Completed'`; shipped and kept | **yes, the only status that does** |
| **Cancelled** | cancelled before shipment (`ship_date` is NULL) | no |
| **Returned** | shipped, then returned and refunded | no |

Returns are modelled at order level: a returned order is excluded in full, with no partial refunds, restocking cost or return shipping.

## KPI definitions

All use completed orders only and INR.

| KPI | Definition | Zero / missing denominator |
|---|---|---|
| Line revenue | `ROUND(quantity × unit_price × (1 − discount), 2)`; `unit_price` is the price charged before discount | n/a |
| Total revenue | sum of line revenue | 0 for an empty selection |
| Total cost | sum of `ROUND(quantity × unit_cost, 2)` | 0 |
| Total profit | revenue − cost; can be negative | 0 |
| Total orders | **distinct** `order_id` | 0 |
| Total customers | distinct `customer_id` with ≥1 completed order in the selection | 0 |
| Profit margin | profit ÷ revenue | BLANK / `None` |
| Average order value | revenue ÷ completed orders (orders, not lines) | BLANK / `None` |
| Cancellation rate | cancelled orders ÷ placed orders | BLANK / `None` |
| Return rate | returned orders ÷ placed orders | BLANK / `None` |

Excluded by design: tax, shipping fees, payment charges, overheads, returns handling. "Profit" is therefore gross profit after product cost only.

### Previous comparable period

| Selected months | Compared with |
|---|---|
| exactly one | the previous calendar month |
| two or more | the same months one year earlier |
| the comparison period is not fully inside the calendar | **no comparison** (blank), never a partial figure |
| the current selection has no completed orders | **no comparison** (blank): a change cannot be measured from nothing, and the cards show "–" |

| Change measure | Formula |
|---|---|
| Revenue / orders / customers / AOV growth | (current − previous) ÷ previous; blank if previous is blank or 0 |
| Profit growth | (current − previous) ÷ \|previous\|; blank if previous is blank or 0 |
| Margin change | (current margin − previous margin) × 100, in percentage points |

Examples with this dataset: Jan 2024 has no comparison (no Dec 2023); Jan 2025 compares with Dec 2024; all 24 months selected has no comparison; Years 2024 + 2025 with March only is blank because March 2023 does not exist.

## Double-counting rules

- `orders` (1) → `order_items` (many). After that join every header attribute repeats once per line, so **never `COUNT(*)` for orders, customers or AOV**: use `COUNT(DISTINCT order_id)` or aggregate to one row per order first (`vw_order_summary`).
- All dimension joins (product, customer, region, date) are many-to-one and cannot multiply rows. `build_fact_sales()` enforces this with `validate="many_to_one"`.
- A product appears at most once per order (checked in `sql/02_data_quality_checks.sql`).
- Customer segment is a customer attribute: orders are attributed to the customer's current segment, not a segment at order time.
- The order's `region_id` is the ship-to region. Regional reporting always uses it, never the customer's home region.

## Cleaning rules

The pipeline is `python/clean_data.py`. Each rule is logged in `data/processed/cleaning_log.csv` (including rules that found nothing) and rejected records are kept in `data/processed/rejected_rows.csv` with the rule id and the raw record. Nothing is dropped silently.

Actions: **dropped** = exact duplicate; **repaired** = value fixed deterministically; **rejected** = row removed and quarantined.

### Orders

| Rule | Defect | Action |
|---|---|---|
| O1 | exact duplicate order rows | dropped (keep first) |
| O1b | same `order_id`, conflicting content | rejected (keep first) |
| O2a/b | `order_date` / `ship_date` as `dd/mm/yyyy` or `dd-Mon-yyyy` | repaired to ISO (day-first, the Indian convention; ambiguity is impossible because both formats are tried only after ISO fails and the generator never emits month-first dates) |
| O2c | `order_date` missing or unparseable | rejected |
| O2d | `order_date` outside the reporting window 2024-01-01…2025-12-31 | rejected |
| O3 | status spelling or case (`completed`, `Canceled`, ` Completed `) | repaired to Completed / Cancelled / Returned |
| O3b | status not in the domain | rejected |
| O4 | `ship_date` earlier than `order_date` | repaired: `ship_date` set to NULL (the order date is trusted, the ship date is not) |
| O4b | cancelled order with a `ship_date` | repaired: set to NULL |
| O5a | `customer_id` missing | rejected: an order that cannot be attributed to a customer would break customer counts |
| O5b | `customer_id` not in customers | rejected |
| O6 | `region_id` missing or unknown | rejected |
| O7 | `sales_channel` missing | repaired to `Unknown` (the sale is real; the channel is not known) |
| O8 | order has no valid lines left after line cleaning | rejected |

### Order lines

| Rule | Defect | Action |
|---|---|---|
| I1 / I1b | exact duplicate line / duplicate `order_item_id` with conflicting data | dropped / rejected |
| I2 | quantity missing, zero or negative | rejected |
| I3 | `unit_price` missing, zero or negative | rejected (no safe imputation for a charged price) |
| I4 | `unit_cost` missing | repaired from the product master standard cost |
| I5 | discount in (1, 100], i.e. entered as a percentage | repaired (÷ 100) |
| I5b | discount missing | repaired to 0 |
| I6 | discount negative or above 100 % after conversion | rejected |
| I7 | `order_id` not in the raw orders (orphan line) | rejected |
| I8 | `product_id` not in products | rejected |
| I9 | line belongs to an order rejected at header level | rejected (cascade) |

### Customers and products

| Rule | Defect | Action |
|---|---|---|
| C1 / C1b | duplicate customer rows | dropped / rejected |
| C2 | segment spelling, case, whitespace | repaired |
| C3 / C3b | segment missing or unrecognised | repaired to `Unknown` (customer still has valid sales and stays in totals) |
| C4 | whitespace in `customer_name` | repaired |
| C5 | `home_region_id` unknown | rejected |
| P1 / P1b | category spelling or case; unknown category | repaired / rejected |
| P2 | whitespace in `product_name` | repaired |
| P3 | list price or standard cost missing, non-positive or cost ≥ price | rejected |
| R1 | duplicate `region_id` | rejected |

Judgement calls worth discussing in an interview: rejecting rather than imputing orders with no customer (affects 26 orders), rejecting rather than guessing a missing `unit_price`, repairing a missing `unit_cost` from the master (a reasonable proxy because standard cost drifts only a few percent per year), and setting a suspicious `ship_date` to NULL rather than rejecting an otherwise good sale.

## Reconciliation tests

| Test | Where |
|---|---|
| Every injected defect is found by exactly one rule and the counts match `data/raw/defect_manifest.json` | `python/validate_data.py` |
| All primary keys unique, all foreign keys resolve | `validate_data.py`, `sql/02_data_quality_checks.sql` |
| `fact_sales` revenue/cost/profit equal the independent recomputation from `order_items` | `validate_data.py`, `tests/` |
| Sum of region, category, segment, channel, product and month breakdowns equals total revenue | `tests/test_data_quality.py` |
| Order count equals the completed orders in `orders` and is below the line count | `tests/`, `sql/04_business_analysis.sql` (`double_count_guard`) |
| 52 SQL result sets equal independently computed pandas results | `python/verify_sql_against_python.py` |
| Power BI cards equal `docs/powerbi_reference_values.md` | manual, after building the report |
