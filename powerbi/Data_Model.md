# Power BI data model

All data is **synthetic**. The model is a star schema: one fact table (one row per order line) surrounded by four dimensions.

```
                         DimDate
                           │ 1
                           │
 DimProduct ─1───────*─ FactSales ─*───────1─ DimCustomer
                           │ *
                           │
                           │ 1
                        DimRegion
```

## Source files

Load these from `data/processed/` (Get data → Text/CSV). Rebuild them any time with `python python/generate_data.py && python python/clean_data.py`.

| Model table | Source file | Grain | Rows (seed 42) |
|---|---|---|---:|
| `FactSales` | `fact_sales.csv` | one order line | 31,540 |
| `DimDate` | `dim_date.csv` | one calendar day, 2024-01-01 to 2025-12-31 | 731 |
| `DimProduct` | `products.csv` | one product | 69 |
| `DimCustomer` | `customers.csv` | one customer | 2,200 |
| `DimRegion` | `regions.csv` | one city (rolls up to state and region) | 22 |

Connecting to MySQL instead: use the MySQL connector and import `vw_fact_sales` (as `FactSales`), `dim_date`, `products`, `customers`, `regions`. `vw_fact_sales` has every column of `fact_sales.csv` (same names) plus the date attributes `cal_year`, `cal_quarter`, `month_num`, `month_name`, `month_key`, `month_label`, which you can drop because `DimDate` supplies them. Its row count and revenue equal `fact_sales.csv` (checked by the `reconciliation_checks` query and by `python/verify_sql_against_python.py`).

`fact_sales.csv` keeps **all** order statuses. Every measure filters to `Completed` (see `DAX_Measures.md`), which is what lets the report also show cancellation and return rates.

## Power Query settings

Apply in Transform data before loading.

| Table | Column | Data type | Notes |
|---|---|---|---|
| FactSales | `order_date`, `ship_date` | Date | `ship_date` is blank for cancelled orders; leave as null |
| FactSales | `quantity`, `is_completed` | Whole number | |
| FactSales | `order_item_id`, `order_id`, `customer_id`, `product_id`, `region_id`, `sales_channel`, `order_status` | Text (`region_id` Whole number) | |
| FactSales | `unit_price`, `unit_cost`, `gross_sales`, `discount_amount`, `line_revenue`, `line_cost`, `line_profit` | Fixed decimal number | avoids floating-point drift in sums |
| FactSales | `discount` | Decimal number | fraction, 0.15 = 15% |
| DimDate | `full_date` | Date | |
| DimDate | `date_key`, `cal_year`, `quarter_num`, `month_num`, `month_key`, `day_of_month`, `week_of_year`, `day_of_week_num`, `is_weekend` | Whole number | |
| DimProduct | `unit_price` → rename **`list_price`**, `unit_cost` → rename **`standard_cost`** | Fixed decimal number | avoids confusion with the transaction-level columns of the same name |
| DimCustomer | `signup_date` | Date | |
| DimCustomer | `home_region_id` | Whole number | deliberately named differently from `region_id` so Power BI does not auto-create a second path to `DimRegion` |

## Relationships

Create in Model view. All are many-to-one, single-direction (dimension filters fact), cross-filter direction *Single*.

| From (many) | To (one) | Active | Notes |
|---|---|---|---|
| `FactSales[order_date]` | `DimDate[full_date]` | Yes | the only date relationship; all time intelligence uses it |
| `FactSales[product_id]` | `DimProduct[product_id]` | Yes | |
| `FactSales[customer_id]` | `DimCustomer[customer_id]` | Yes | |
| `FactSales[region_id]` | `DimRegion[region_id]` | Yes | `region_id` on the fact is the order's ship-to region and drives all regional reporting |

Do **not** relate `DimCustomer[home_region_id]` to `DimRegion`: it would create an ambiguous second path from the fact to the region dimension. (In this synthetic data the home and ship-to regions are the same, which is why the choice does not change any number; the rule matters for real data.)

Optional extension: an *inactive* relationship `FactSales[ship_date]` → `DimDate[full_date]` activated with `USERELATIONSHIP` for shipping analysis. Not used by this report.

After loading: **Table tools → Mark as date table → `DimDate[full_date]`.**

## Column properties

| Table | Column | Setting |
|---|---|---|
| DimDate | `month_name` | Sort by column → `month_num` |
| DimDate | `month_short` | Sort by column → `month_num` |
| DimDate | `month_label` | Sort by column → `month_key` (this is what makes "Jan 2024 … Dec 2025" chronological, not alphabetical) |
| DimDate | `year_quarter` | No sort column needed: the `YYYY-Qn` text sorts chronologically on its own |
| DimDate | `day_name` | Sort by column → `day_of_week_num` |
| DimCustomer | `customer_name` | none (display only); use `customer_id` for ranking |
| DimRegion | `region` | Data category: none; keep `state`, `city` for drill-down (Region → State → City hierarchy) |
| All | key columns (`*_id`, `date_key`, `month_key`) | Hide in report view; they are for relationships and sorting |
| FactSales | numeric columns | Hide, with *Default summarization → Don't summarize*; reports use measures only |

Hierarchies: `DimDate` Year → Quarter → Month (`cal_year`, `cal_quarter`, `month_label`); `DimProduct` Category → Subcategory → Product; `DimRegion` Region → State → City.

## Date table

`dim_date.csv` is a continuous calendar (731 days, 24 consecutive months, validated by `python/validate_data.py` and by the `dim_date_*` checks in `sql/02_data_quality_checks.sql`). Fields:

| Column | Example | Purpose |
|---|---|---|
| `full_date` | 2025-03-14 | relationship key |
| `cal_year` | 2025 | Year slicer |
| `cal_quarter`, `year_quarter` | Q1, 2025-Q1 | quarter |
| `month_num`, `month_name`, `month_short` | 3, March, Mar | Month slicer (sorted by `month_num`) |
| `month_key` | 202503 | integer year-month; drives previous-period logic and sort order |
| `month_label` | Mar 2025 | chart axis label |

## Measures table

A disconnected table `_Measures` holds all measures (see `DAX_Measures.md`). Display folders: *1 Core KPIs*, *2 Previous period*, *3 Growth*, *4 Display*, *5 Selected period & rank*, *6 Insights*.

## Model-level assumptions

- Currency is INR everywhere; there is no multi-currency conversion.
- Revenue is net of discount and excludes tax and shipping (neither is modelled).
- Only `Completed` orders count towards revenue, cost, profit, orders, customers, margin and AOV. `Cancelled` orders never shipped; `Returned` orders were refunded. Both stay in the fact table for status reporting.
- Customer segment `Unknown` (customers whose source record had no segment) is kept in the model and visible in the slicer rather than dropped, so totals reconcile.
- A product appears at most once per order (lines are aggregated at entry); this is checked in `sql/02_data_quality_checks.sql`.

## Validation after building the model

1. Row counts in Model view / Table view match the table above.
2. With no slicers, the six KPI cards equal scenario **A** in `docs/powerbi_reference_values.md` (revenue ₹265,860,607.20, 15,151 orders, 1,858 customers).
3. Repeat for the other scenarios in that file, especially **D** (month vs previous month), **F** (January crossing the year boundary), **C/E** (comparison must be blank) and **J** (two Marches).
