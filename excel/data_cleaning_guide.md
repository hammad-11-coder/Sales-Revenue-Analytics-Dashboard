# Excel data inspection and cleaning guide

All data is **synthetic**. This guide shows how to inspect and clean the raw CSVs in Excel, which is the first stage of the project's workflow. The same rules are automated in `python/clean_data.py`; the Excel route is for learning, spot checks, and for showing the method in an interview. Rule ids (O3, I2, …) match [`docs/business_rules.md`](../docs/business_rules.md#cleaning-rules) and `data/processed/cleaning_log.csv`.

You can skip this guide entirely: the cleaned files are already in `data/processed/`.

> **Verification status.** The Excel / Power Query steps below were not executed in the authoring environment (Excel was not available). The rules they implement *were* executed and verified in Python (`python/clean_data.py`, `python/validate_data.py`). Treat the M expressions as starting points and compare your row counts with the expected values; if a count differs, the Python pipeline is the reference.

## 1. Open the data safely

1. **Data → From Text/CSV** (not double-click) for each file in `data/raw/`. Set *File origin* to UTF-8.
2. Click **Transform Data** so that Power Query shows the real text before Excel guesses types.
3. For `orders.csv`, set `order_date` and `ship_date` to **Text** first. Excel's automatic date detection reads `04/03/2025` as 3 April or 4 March depending on your regional settings and silently corrupts the data.
4. Load each table as an **Excel Table** (Ctrl+T) named `tblOrders`, `tblItems`, `tblCustomers`, `tblProducts`, `tblRegions`.

## 2. Profile first, change later

| Question | Technique |
|---|---|
| How many rows, columns, blanks? | Power Query → **View → Column quality / Column distribution / Column profile** (turn on *Column profiling based on entire data set*) |
| Which values appear, and how often? | PivotTable with the column in Rows and `order_id` count in Values (shows `completed`, `Canceled`, ` Completed ` as separate rows) |
| Duplicates? | **Home → Remove Rows → Remove Duplicates** preview, or `=COUNTIFS(tblOrders[order_id], [@[order_id]])>1` in a helper column |
| Outliers? | PivotTable min / max of `quantity`, `unit_price`, `discount`; **Conditional Formatting → Top/Bottom** |

Write down what you find before fixing anything. Expected findings for seed 42: 68 duplicate order rows, 95 duplicate lines, 7 duplicate customers, 682 status spelling variants, 852 dates in non-ISO formats (511 order, 341 ship), 85 missing channels, 26 missing customer ids, 48 bad quantities, 32 bad prices, 127 percentage-style discounts.

## 3. Cleaning steps (and the rule each one implements)

Do these in Power Query so every step is recorded and repeatable (the *Applied Steps* list is your cleaning log).

| Step | Excel / Power Query | Rule |
|---|---|---|
| Remove exact duplicate rows | select all columns → **Remove Duplicates** | O1, I1, C1 |
| Standardise status | **Transform → Format → Trim**, then **Lowercase**, then **Replace Values** (`canceled` → `cancelled`), then **Capitalize Each Word** | O3 |
| Standardise segment and category | Trim, lowercase, capitalise each word; fix `Home & Kitchen` and `Small Business` by hand with Replace Values | C2, P1 |
| Collapse whitespace in names | `Text.Combine(List.Select(Text.Split([customer_name]," "), each _ <> "")," ")` as a custom column | C4, P2 |
| Parse dates | Add column → `Date.From(Text.Trim([order_date]))` fails on `dd/mm/yyyy`; instead use `try Date.FromText([order_date], "en-IN") otherwise null` (or *Using Locale → English (India)* on the type change) | O2a/b |
| Impossible ship date | Custom column `if [ship_date] < [order_date] then null else [ship_date]` | O4 |
| Missing channel | **Replace Values** (null → `Unknown`) | O7 |
| Missing segment | **Replace Values** (null → `Unknown`) | C3 |
| Discount entered as a percentage | `if [discount] > 1 then [discount]/100 else [discount]` | I5 |
| Missing unit cost | **Merge Queries** with `products` on `product_id`, then `if [unit_cost] = null then [products.unit_cost] else [unit_cost]` | I4 |

Rows to remove (and keep a copy of on a separate sheet named `Rejected`, never just delete):

| Filter | Rule | Expected rows |
|---|---|---:|
| `quantity` ≤ 0 | I2 | 48 |
| `unit_price` ≤ 0 or blank | I3 | 32 |
| `discount` < 0 | I6 | 16 |
| `product_id` not in products (Merge → Left Anti) | I8 | 32 |
| `order_id` not in orders (Merge → Left Anti) | I7 | 32 |
| orders with blank `customer_id` | O5a | 26 |
| order lines belonging to those orders (Left Anti) | I9 | 45 |

## 4. Validate in Excel

Build a small `Checks` sheet with formulas next to the expected values; every check should read `OK`.

| Check | Formula idea |
|---|---|
| Row counts | `=ROWS(tblOrders)` equals 16,990; `=ROWS(tblItems)` equals 31,540 |
| Unique keys | `=ROWS(tblOrders)=ROWS(UNIQUE(tblOrders[order_id]))` |
| Valid status | `=SUMPRODUCT(--ISNA(MATCH(tblOrders[order_status],{"Completed","Cancelled","Returned"},0)))=0` |
| Line revenue | add `=[@quantity]*[@unit_price]*(1-[@discount])` per line, then `=SUM()` for Completed orders (use `SUMIFS` through a lookup column) |
| No orphans | `=SUMPRODUCT(--ISNA(MATCH(tblItems[order_id],tblOrders[order_id],0)))=0` |

## 5. First exploratory analysis in Excel

Before moving to SQL and Power BI, answer these with PivotTables (filter `order_status = Completed`):

1. Revenue and profit by month: is there a seasonal peak?
2. Revenue and margin by category: which category is large but thin-margin?
3. Revenue by region.
4. Top 10 products and top 5 customers by revenue.

Add a **Timeline** slicer on `order_date` and slicers for region and category to rehearse the interactions the Power BI report will have. The headline answers are in [`docs/key_insights.md`](../docs/key_insights.md): check yours against them.

## 6. Save the result

Export the cleaned tables as CSV (UTF-8) to `data/processed/` only if you want to compare them with the pipeline's output. A quick comparison is the Excel row counts above against `data/processed/cleaning_summary.json`.
