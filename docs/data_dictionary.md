# Data dictionary

**All data is synthetic.** Names, prices, volumes and every figure are generated from a fixed random seed (`python/generate_data.py`, seed 42). Customer names are random combinations of common first and last names; no real person or company is represented. Currency is Indian rupees (₹), dates are ISO `YYYY-MM-DD`.

Two layers exist:

- `data/raw/`: the five source extracts **with deliberately injected defects** (duplicates, mixed date formats, bad quantities, orphan keys, …) plus `defect_manifest.json`, which records exactly what was injected.
- `data/processed/`: the cleaned, analysis-ready tables plus `dim_date.csv`, `fact_sales.csv`, `cleaning_log.csv` and `rejected_rows.csv`.

Row counts (seed 42):

| Table | Raw | Processed |
|---|---:|---:|
| regions | 22 | 22 |
| products | 69 | 69 |
| customers | 2,207 | 2,200 |
| orders | 17,111 | 16,990 |
| order_items | 31,840 | 31,540 |
| dim_date | n/a | 731 |
| fact_sales | n/a | 31,540 |
| rejected_rows | n/a | 258 |

## regions

One row per city. `region` is the sales region used in reporting.

| Column | Type | Description |
|---|---|---|
| `region_id` | int, PK | |
| `region` | text | North, South, East, West, Central |
| `state` | text | |
| `city` | text | (`state`, `city`) is unique |

## products

| Column | Type | Description |
|---|---|---|
| `product_id` | text, PK | `P001` … `P069` |
| `product_name` | text | fictional product names |
| `category` | text | Technology, Furniture, Office Supplies, Home & Kitchen, Apparel |
| `subcategory` | text | 16 subcategories |
| `unit_price` | decimal | list price in ₹ (base year) |
| `unit_cost` | decimal | standard cost in ₹; always below list price |

## customers

| Column | Type | Description |
|---|---|---|
| `customer_id` | text, PK | `C0001` … `C2200` |
| `customer_name` | text | synthetic, fictional |
| `segment` | text | Consumer, Corporate, Small Business, or `Unknown` (source segment missing) |
| `home_region_id` | int, FK → regions | the customer's home city. Not used for regional reporting |
| `signup_date` | date | |

No emails, phone numbers, addresses or other personal identifiers exist in the dataset.

## orders (order header, one row per order)

| Column | Type | Description |
|---|---|---|
| `order_id` | text, PK | `ORD-YYYY-NNNNNN` |
| `order_date` | date, FK → dim_date | |
| `ship_date` | date, nullable | NULL for cancelled orders and where the source value was unreliable (rule O4) |
| `customer_id` | text, FK → customers | |
| `region_id` | int, FK → regions | **ship-to** city; drives regional reporting |
| `sales_channel` | text | Online, Marketplace, Mobile App, Retail Store, or `Unknown` |
| `order_status` | text | Completed, Cancelled, Returned |

## order_items (order line, one row per product per order)

| Column | Type | Description |
|---|---|---|
| `order_item_id` | int, PK | |
| `order_id` | text, FK → orders | |
| `product_id` | text, FK → products | at most once per order |
| `quantity` | int | > 0 |
| `unit_price` | decimal | price charged per unit before discount (₹); drifts slightly by year versus the product list price |
| `unit_cost` | decimal | cost per unit (₹) |
| `discount` | decimal | fraction in [0, 1], e.g. 0.15 = 15 % off |

## dim_date (continuous calendar, 731 days: 2024-01-01 … 2025-12-31)

| Column | Example | Description |
|---|---|---|
| `date_key` | 20250314 | integer key |
| `full_date` | 2025-03-14 | relationship key |
| `cal_year` | 2025 | |
| `quarter_num`, `cal_quarter`, `year_quarter` | 1, Q1, 2025-Q1 | |
| `month_num`, `month_name`, `month_short` | 3, March, Mar | |
| `month_key` | 202503 | year-month integer; sorts chronologically; used for previous-period logic |
| `month_label` | Mar 2025 | display label; sort by `month_key` |
| `day_of_month`, `week_of_year`, `day_of_week_num`, `day_name`, `is_weekend` | | |

`YEAR_MONTH` is a reserved word in MySQL, which is why the year-month fields are `month_key` and `month_label`.

## fact_sales (Power BI fact table, one row per order line, all statuses)

Built by `kpi_definitions.build_fact_sales()` and mirrored by the SQL view `vw_fact_sales`.

| Column | Description |
|---|---|
| `order_item_id`, `order_id`, `product_id`, `customer_id`, `region_id` | keys |
| `order_date`, `ship_date`, `sales_channel`, `order_status` | from the order header |
| `quantity`, `unit_price`, `unit_cost`, `discount` | from the line |
| `gross_sales` | `ROUND(quantity × unit_price, 2)` |
| `discount_amount` | `gross_sales − line_revenue` |
| `line_revenue` | `ROUND(quantity × unit_price × (1 − discount), 2)` |
| `line_cost` | `ROUND(quantity × unit_cost, 2)` |
| `line_profit` | `line_revenue − line_cost` (can be negative) |
| `is_completed` | 1 if `order_status = 'Completed'` |

Measures count only `is_completed = 1` rows.

## cleaning_log.csv

| Column | Description |
|---|---|
| `rule_id` | e.g. `O3`; defined in [`business_rules.md`](business_rules.md#cleaning-rules) |
| `table` | table the rule applies to |
| `description` | what the rule checks |
| `action` | dropped / repaired / rejected |
| `rows_affected` | rows found (0 means the rule ran and found nothing) |

## rejected_rows.csv

| Column | Description |
|---|---|
| `table`, `rule_id`, `reason` | which rule rejected the record and why |
| `record_key` | primary key of the rejected record |
| `raw_record` | the full raw record as JSON, so it can be audited or repaired upstream |

## defect_manifest.json (raw layer)

Counts of each defect injected by `generate_data.py` (for example `orders_status_variants: 682`) and the row counts of the clean ground truth. `validate_data.py` asserts that each cleaning rule found exactly its injected count. A real-world dataset would have no such manifest; it exists here so the cleaning logic can be tested against a known answer.

## Generated, not real: what the data does and does not model

Modelled: seasonality (festive peak in October and November, soft February and June), about 15 % order growth between the two years, a heavy-tailed customer value distribution, regional mix, channel mix, category margin differences, discounting depth by category and season, an inflating Furniture cost base, order cancellations (~5 %) and returns (~6 %).

Not modelled: tax (GST), shipping fees, payment fees, inventory, promotions as entities, customer acquisition cost, multiple currencies, partial returns. Results describe this generated data only.
