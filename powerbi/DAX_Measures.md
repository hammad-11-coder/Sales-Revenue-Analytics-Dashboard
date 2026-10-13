# DAX measures

> **Status: not executed.** These measures were written to match the SQL and Python logic that *was* executed and verified
> (`python/verify_sql_against_python.py`), but Power BI Desktop was not available where this project was authored, so the DAX itself
> has not been run. Paste the measures in, then check the cards against `docs/powerbi_reference_values.md`. Any number that
> differs by more than ₹0.01 points to a measure, relationship or data-type problem.

All data is **synthetic**. Table and column names follow `powerbi/Data_Model.md` (snake_case columns exactly as they appear in the CSVs).

## Conventions

- Create a table called `_Measures` (Enter Data, one blank column, then hide the column) and put every measure in it, grouped in display folders named as the `##` headings below.
- **Revenue recognition rule:** every money, order and customer measure counts `FactSales[order_status] = "Completed"` only. Cancelled orders never shipped and Returned orders were refunded. The fact table keeps all statuses so that cancellation and return rates can be reported.
- **Division is always `DIVIDE`**, so a zero or blank denominator returns BLANK instead of an error.
- **Variables before iterators.** Several measures call other measures inside `FILTER`/`TOPN`/`SUMX`. A measure called inside an iterator is re-evaluated *per row* (context transition), so any value that must come from the *outer* selection is captured in a `VAR` first.
- Formats: set money measures to *Currency → ₹ English (India)* with 0 decimals; percentages to `0.0%`.

---

## 1. Core KPIs

```dax
Total Revenue =
CALCULATE ( SUM ( FactSales[line_revenue] ), FactSales[order_status] = "Completed" )
```
Net sales after discount, completed orders only. `line_revenue = ROUND(quantity * unit_price * (1 - discount), 2)` is stored per line in the data.

```dax
Total Cost =
CALCULATE ( SUM ( FactSales[line_cost] ), FactSales[order_status] = "Completed" )
```

```dax
Total Profit = [Total Revenue] - [Total Cost]
```
Can be negative; nothing in the report assumes a positive value.

```dax
Total Orders =
VAR _n = CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ), FactSales[order_status] = "Completed" )
RETURN IF ( _n = 0, BLANK (), _n )
```
`DISTINCTCOUNT` on `order_id` (not a row count) because the fact has one row per order *line*.

```dax
Total Customers =
VAR _n = CALCULATE ( DISTINCTCOUNT ( FactSales[customer_id] ), FactSales[order_status] = "Completed" )
RETURN IF ( _n = 0, BLANK (), _n )
```
Customers with at least one completed order in the current selection.

```dax
Profit Margin = DIVIDE ( [Total Profit], [Total Revenue] )
```

```dax
Average Order Value = DIVIDE ( [Total Revenue], [Total Orders] )
```

### Order-status measures (reporting extras)

```dax
Placed Orders = DISTINCTCOUNT ( FactSales[order_id] )

Cancelled Orders =
CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ), FactSales[order_status] = "Cancelled" )

Returned Orders =
CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ), FactSales[order_status] = "Returned" )

Cancellation Rate = DIVIDE ( [Cancelled Orders], [Placed Orders] )
Return Rate       = DIVIDE ( [Returned Orders],  [Placed Orders] )
```

---

## 2. Previous-period machinery

**Rule (identical in Python `comparison_plan()` and the Streamlit app):**

| Months in the current date selection | Compared with |
|---|---|
| exactly 1 | the previous calendar month (`MoM`) |
| 2 or more | the same months one year earlier (`YoY`) |
| any prior month is outside the calendar | **no comparison** (BLANK), never a partial figure |

Whole months are always compared with whole months (shifted `month_key` values), so a 29-day February is not compared with a 28-day one day by day.

```dax
Selected Months = DISTINCTCOUNT ( DimDate[month_key] )
```
Number of distinct months visible in `DimDate` under the current slicers (a chart point on a month axis has 1).

```dax
Comparison Mode =
SWITCH ( TRUE (),
    [Selected Months] = 1, "MoM",
    [Selected Months] > 1, "YoY",
    "NONE" )
```

```dax
Comparison Shift (Months) =
SWITCH ( [Comparison Mode], "MoM", -1, "YoY", -12, BLANK () )
```

```dax
Prior Period Available =
VAR _shift = [Comparison Shift (Months)]
VAR _priorKeys =
    SELECTCOLUMNS (
        VALUES ( DimDate[month_key] ),
        "k",
            VAR _idx = INT ( DimDate[month_key] / 100 ) * 12 + MOD ( DimDate[month_key], 100 ) - 1 + _shift
            RETURN INT ( _idx / 12 ) * 100 + MOD ( _idx, 12 ) + 1
    )
VAR _cur = [Selected Months]
VAR _found =
    CALCULATE ( DISTINCTCOUNT ( DimDate[month_key] ),
                REMOVEFILTERS ( DimDate ),
                TREATAS ( _priorKeys, DimDate[month_key] ) )
RETURN
    NOT ISBLANK ( _shift ) && _cur > 0 && _found = _cur
```
**How the prior period is built.** Each selected `month_key` (yyyymm) is converted to a month index (`year × 12 + month − 1`), shifted by -1 or -12 months and converted back to a key. The resulting set of keys is applied to `DimDate[month_key]` with `TREATAS` after the date slicers are cleared with `REMOVEFILTERS ( DimDate )`. Keys that do not exist in the calendar are ignored by `TREATAS`, so a prior period that runs off the start of the data finds fewer months than were selected and `Prior Period Available` is FALSE.

Why not `PARALLELPERIOD` here? It shifts only the first and last selected dates and returns *every* date in between, so a non-contiguous selection such as Jan + Mar would be compared with Jan to Mar of the prior year (three months against two). Shifting the individual month keys handles any selection, matches `comparison_plan()` in `python/kpi_definitions.py`, and works at the month grain the rules are written in.

```dax
Comparison Label =
IF ( [Prior Period Available],
     SWITCH ( [Comparison Mode], "MoM", "vs previous month", "YoY", "vs same period last year" ) )
```

**Why `REMOVEFILTERS ( DimDate )`?** A Year slicer filters `DimDate[cal_year]`. If that filter survived, "previous year" would intersect with the selected year and return nothing. The prior keys are computed from the *outer* selection (in the `VAR` before `CALCULATE`), and the leftover date filters are then cleared.

```dax
Previous Period Revenue =
VAR _shift = [Comparison Shift (Months)]
VAR _priorKeys =
    SELECTCOLUMNS (
        VALUES ( DimDate[month_key] ),
        "k",
            VAR _idx = INT ( DimDate[month_key] / 100 ) * 12 + MOD ( DimDate[month_key], 100 ) - 1 + _shift
            RETURN INT ( _idx / 12 ) * 100 + MOD ( _idx, 12 ) + 1
    )
RETURN
    IF ( [Prior Period Available],
         CALCULATE ( [Total Revenue],
                     REMOVEFILTERS ( DimDate ),
                     TREATAS ( _priorKeys, DimDate[month_key] ) ) )

Previous Period Profit =
VAR _shift = [Comparison Shift (Months)]
VAR _priorKeys =
    SELECTCOLUMNS (
        VALUES ( DimDate[month_key] ),
        "k",
            VAR _idx = INT ( DimDate[month_key] / 100 ) * 12 + MOD ( DimDate[month_key], 100 ) - 1 + _shift
            RETURN INT ( _idx / 12 ) * 100 + MOD ( _idx, 12 ) + 1
    )
RETURN
    IF ( [Prior Period Available],
         CALCULATE ( [Total Profit],
                     REMOVEFILTERS ( DimDate ),
                     TREATAS ( _priorKeys, DimDate[month_key] ) ) )

Previous Period Orders =
VAR _shift = [Comparison Shift (Months)]
VAR _priorKeys =
    SELECTCOLUMNS (
        VALUES ( DimDate[month_key] ),
        "k",
            VAR _idx = INT ( DimDate[month_key] / 100 ) * 12 + MOD ( DimDate[month_key], 100 ) - 1 + _shift
            RETURN INT ( _idx / 12 ) * 100 + MOD ( _idx, 12 ) + 1
    )
RETURN
    IF ( [Prior Period Available],
         CALCULATE ( [Total Orders],
                     REMOVEFILTERS ( DimDate ),
                     TREATAS ( _priorKeys, DimDate[month_key] ) ) )

Previous Period Customers =
VAR _shift = [Comparison Shift (Months)]
VAR _priorKeys =
    SELECTCOLUMNS (
        VALUES ( DimDate[month_key] ),
        "k",
            VAR _idx = INT ( DimDate[month_key] / 100 ) * 12 + MOD ( DimDate[month_key], 100 ) - 1 + _shift
            RETURN INT ( _idx / 12 ) * 100 + MOD ( _idx, 12 ) + 1
    )
RETURN
    IF ( [Prior Period Available],
         CALCULATE ( [Total Customers],
                     REMOVEFILTERS ( DimDate ),
                     TREATAS ( _priorKeys, DimDate[month_key] ) ) )

Previous Period Margin = DIVIDE ( [Previous Period Profit], [Previous Period Revenue] )
Previous Period AOV    = DIVIDE ( [Previous Period Revenue], [Previous Period Orders] )
```

### Explicit month-over-month and year-over-year measures (named in the brief)

These use `PARALLELPERIOD` and are meant for **one month at a time** (a point on the month axis, or a tooltip), where the shifted range is exactly one month. `Previous Month Revenue/Profit` return BLANK when more than one month is in the current filter context, so they can never show a misleading shifted range. The KPI cards use the key-based measures above, which also handle multi-month and non-contiguous selections.

```dax
Previous Month Revenue =
IF ( [Selected Months] = 1,
     CALCULATE ( [Total Revenue],
                 REMOVEFILTERS ( DimDate ),
                 PARALLELPERIOD ( DimDate[full_date], -1, MONTH ) ) )

Previous Month Profit =
IF ( [Selected Months] = 1,
     CALCULATE ( [Total Profit],
                 REMOVEFILTERS ( DimDate ),
                 PARALLELPERIOD ( DimDate[full_date], -1, MONTH ) ) )

Revenue Same Period LY =
CALCULATE ( [Total Revenue],
            REMOVEFILTERS ( DimDate ),
            PARALLELPERIOD ( DimDate[full_date], -12, MONTH ) )

Profit Same Period LY =
CALCULATE ( [Total Profit],
            REMOVEFILTERS ( DimDate ),
            PARALLELPERIOD ( DimDate[full_date], -12, MONTH ) )
```
Use these in chart tooltips and for the optional year-over-year line on the trend chart (`Revenue Same Period LY` for Jan 2024 is BLANK because 2023 is outside the calendar).

---

## 3. Growth measures (feed the KPI-card deltas)

```dax
Revenue Growth % =
VAR _prev = [Previous Period Revenue]
RETURN IF ( NOT ISBLANK ( _prev ) && _prev <> 0 && NOT ISBLANK ( [Total Revenue] ), DIVIDE ( [Total Revenue] - _prev, _prev ) )

Profit Growth % =
VAR _prev = [Previous Period Profit]
RETURN IF ( NOT ISBLANK ( _prev ) && _prev <> 0 && NOT ISBLANK ( [Total Profit] ), DIVIDE ( [Total Profit] - _prev, ABS ( _prev ) ) )

Orders Growth % =
VAR _prev = [Previous Period Orders]
RETURN IF ( NOT ISBLANK ( _prev ) && _prev <> 0 && NOT ISBLANK ( [Total Orders] ), DIVIDE ( [Total Orders] - _prev, _prev ) )

Customers Growth % =
VAR _prev = [Previous Period Customers]
RETURN IF ( NOT ISBLANK ( _prev ) && _prev <> 0 && NOT ISBLANK ( [Total Customers] ), DIVIDE ( [Total Customers] - _prev, _prev ) )

AOV Growth % =
VAR _prev = [Previous Period AOV]
RETURN IF ( NOT ISBLANK ( _prev ) && _prev <> 0 && NOT ISBLANK ( [Average Order Value] ), DIVIDE ( [Average Order Value] - _prev, _prev ) )

Profit Margin Change (pp) =
VAR _prev = [Previous Period Margin]
RETURN IF ( NOT ISBLANK ( _prev ) && NOT ISBLANK ( [Profit Margin] ), ( [Profit Margin] - _prev ) * 100 )
```
Assumptions: a blank or zero prior value, or an empty *current* selection, gives BLANK (shown as "–"), not ±100% or infinity. (Without the `NOT ISBLANK ( [current] )` guard, an empty selection whose prior period had sales would compute `BLANK - prev` and show a false "▼ 100%".) `Profit Growth %` divides by `ABS(prev)` so that going from a loss to a smaller loss reads as an improvement.

### Conditional indicators (use as text and as *Field value* font colours)

```dax
Revenue Change Label =
VAR _g = [Revenue Growth %]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.0%" ) )

Profit Change Label =
VAR _g = [Profit Growth %]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.0%" ) )

Orders Change Label =
VAR _g = [Orders Growth %]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.0%" ) )

Customers Change Label =
VAR _g = [Customers Growth %]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.0%" ) )

Margin Change Label =
VAR _g = [Profit Margin Change (pp)]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.00" ) & " pp" )

AOV Change Label =
VAR _g = [AOV Growth %]
RETURN IF ( ISBLANK ( _g ), "–", IF ( _g >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( _g ), "0.0%" ) )
```

```dax
Revenue Change Color =
VAR _g = [Revenue Growth %]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )

Profit Change Color =
VAR _g = [Profit Growth %]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )

Orders Change Color =
VAR _g = [Orders Growth %]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )

Customers Change Color =
VAR _g = [Customers Growth %]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )

AOV Change Color =
VAR _g = [AOV Growth %]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )

Margin Change Color =
VAR _g = [Profit Margin Change (pp)]
RETURN SWITCH ( TRUE (), ISBLANK ( _g ), "#6B7280", _g >= 0, "#15803D", "#B91C1C" )
```
Grey = no comparison, green = up, red = down.

---

## 4. Display helpers (compact rupee text for cards)

Power BI's built-in number formats cannot show lakh/crore units, so the cards use text measures. Full values stay available in tooltips.

```dax
Total Revenue (Display) =
VAR _v = [Total Revenue]
RETURN
    IF ( ISBLANK ( _v ), "–",
         IF ( _v < 0, "-", "" ) & "₹"
         & SWITCH ( TRUE (),
               ABS ( _v ) >= 10000000, FORMAT ( ABS ( _v ) / 10000000, "#,##0.00" ) & " Cr",
               ABS ( _v ) >= 100000,   FORMAT ( ABS ( _v ) / 100000,   "#,##0.00" ) & " L",
               FORMAT ( ABS ( _v ), "#,##0" ) ) )

Total Profit (Display) =
VAR _v = [Total Profit]
RETURN
    IF ( ISBLANK ( _v ), "–",
         IF ( _v < 0, "-", "" ) & "₹"
         & SWITCH ( TRUE (),
               ABS ( _v ) >= 10000000, FORMAT ( ABS ( _v ) / 10000000, "#,##0.00" ) & " Cr",
               ABS ( _v ) >= 100000,   FORMAT ( ABS ( _v ) / 100000,   "#,##0.00" ) & " L",
               FORMAT ( ABS ( _v ), "#,##0" ) ) )

Average Order Value (Display) =
VAR _v = [Average Order Value]
RETURN
    IF ( ISBLANK ( _v ), "–",
         "₹" & SWITCH ( TRUE (),
               _v >= 10000000, FORMAT ( _v / 10000000, "#,##0.00" ) & " Cr",
               _v >= 100000,   FORMAT ( _v / 100000,   "#,##0.00" ) & " L",
               FORMAT ( _v, "#,##0" ) ) )

Revenue (₹ Cr) = DIVIDE ( [Total Revenue], 10000000 )
Profit (₹ Cr)  = DIVIDE ( [Total Profit],  10000000 )
```
Number-only measures for chart axes and data labels (format `0.00`, axis title "₹ crore") so the revenue and profit series always share one clear unit. Tooltips show the full rupee measures.

```dax
Reporting Period =
VAR _first = CALCULATE ( MIN ( FactSales[order_date] ), REMOVEFILTERS () )
VAR _last  = CALCULATE ( MAX ( FactSales[order_date] ), REMOVEFILTERS () )
RETURN FORMAT ( _first, "mmm yyyy" ) & " – " & FORMAT ( _last, "mmm yyyy" )
```
`Reporting Period` deliberately ignores slicers: it describes the dataset, not the selection.

---

## 5. Selected-period, share and ranking measures

```dax
Revenue by Selected Period =
CALCULATE ( [Total Revenue], ALLSELECTED ( DimDate ) )
```
Revenue for the period chosen in the Year/Month slicers, even inside a visual that splits by month. Use it in tooltips ("this month vs the whole selected period").

```dax
Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED () ) )
```
Share of revenue inside the slicer selection; works for the category doughnut, the region bars and the product list.

```dax
Product Rank =
IF ( NOT ISBLANK ( [Total Revenue] ),
     RANKX ( ALLSELECTED ( DimProduct[product_name] ), [Total Revenue], , DESC, SKIP ) )

Customer Rank =
IF ( NOT ISBLANK ( [Total Revenue] ),
     RANKX ( ALLSELECTED ( DimCustomer[customer_id] ), [Total Revenue], , DESC, SKIP ) )
```
`SKIP` gives the same tie behaviour as SQL `RANK()` (1, 2, 2, 4). Put only the entity column (product name / customer id) on the visual's rows, because `ALLSELECTED(column)` keeps any other row-level filters the visual adds and the rank would restart inside each group. The rank reacts to every slicer because `ALLSELECTED` keeps slicer filters but drops the visual's own row filter. Products or customers with no completed revenue in the selection show no rank.

### Conditional-formatting helpers

```dax
Region Rank =
IF ( NOT ISBLANK ( [Total Revenue] ),
     RANKX ( ALLSELECTED ( DimRegion[region] ), [Total Revenue], , DESC, SKIP ) )

Weakest Region Rank =
MAXX ( ALLSELECTED ( DimRegion[region] ), [Region Rank] )

Region Highlight Color =
VAR _rank = [Region Rank]
RETURN SWITCH ( TRUE (),
    ISBLANK ( _rank ), "#9CA3AF",
    _rank = 1, "#15803D",                                  -- strongest region
    _rank = [Weakest Region Rank], "#C2410C",              -- weakest region (ties share the colour)
    "#1D4ED8" )

Category Profit Color =
VAR _overall = CALCULATE ( [Profit Margin], ALLSELECTED ( DimProduct[category] ) )
RETURN SWITCH ( TRUE (),
    ISBLANK ( [Total Profit] ), "#9CA3AF",
    [Total Profit] < 0, "#B91C1C",                         -- loss-making
    [Profit Margin] < _overall / 2, "#C2410C",             -- margin below half the selection's average
    "#1D4ED8" )
```
The "low profit" threshold (half the selection's own margin) is a design choice; change it to a fixed target if the business has one. No category is assumed profitable: the red rule fires whenever the filtered profit is below zero.

---

## 6. Dynamic business insights

Everything below recalculates with the slicers. Each text measure returns a plain "no data" sentence for an empty selection.

```dax
Top Region =
IF ( NOT ISBLANK ( [Total Revenue] ),
     MAXX ( TOPN ( 1,
                   FILTER ( VALUES ( DimRegion[region] ), NOT ISBLANK ( [Total Revenue] ) ),
                   [Total Revenue], DESC ),
            DimRegion[region] ) )

Top Profit Category =
IF ( NOT ISBLANK ( [Total Revenue] ),
     MAXX ( TOPN ( 1,
                   FILTER ( VALUES ( DimProduct[category] ), NOT ISBLANK ( [Total Revenue] ) ),
                   [Total Profit], DESC ),
            DimProduct[category] ) )

Lowest Margin Category =
IF ( NOT ISBLANK ( [Total Revenue] ),
     MAXX ( TOPN ( 1,
                   FILTER ( VALUES ( DimProduct[category] ), NOT ISBLANK ( [Total Revenue] ) ),
                   [Profit Margin], ASC ),
            DimProduct[category] ) )

Top Product =
IF ( NOT ISBLANK ( [Total Revenue] ),
     MAXX ( TOPN ( 1,
                   FILTER ( VALUES ( DimProduct[product_name] ), NOT ISBLANK ( [Total Revenue] ) ),
                   [Total Revenue], DESC ),
            DimProduct[product_name] ) )

Top 5 Customer Revenue Share =
VAR _top5 =
    TOPN ( 5,
           FILTER ( VALUES ( DimCustomer[customer_id] ), NOT ISBLANK ( [Total Revenue] ) ),
           [Total Revenue], DESC )
RETURN DIVIDE ( SUMX ( _top5, [Total Revenue] ), [Total Revenue] )
```
`MAXX(TOPN(1, …), column)` returns the winner's name; if two rows tie, the alphabetically last name is returned, so the text is deterministic. `TOPN(5, …)` can return more than five customers when the 5th place is tied.

```dax
Insight 1 - Revenue Trend =
VAR _g = [Revenue Growth %]
RETURN
    IF ( ISBLANK ( [Total Revenue] ),
         "No sales for the current selection.",
         "Revenue is " & [Total Revenue (Display)]
         & IF ( ISBLANK ( _g ),
                " (no comparable period for this selection). Profit margin is "
                    & FORMAT ( [Profit Margin], "0.0%" ) & ".",
                ", " & IF ( _g >= 0, "up ", "down " ) & FORMAT ( ABS ( _g ), "0.0%" ) & " "
                    & [Comparison Label] & ". Profit margin is "
                    & FORMAT ( [Profit Margin], "0.0%" ) & "." ) )

Insight 2 - Best Region =
VAR _name  = [Top Region]
VAR _rev   = CALCULATE ( [Total Revenue], DimRegion[region] = _name )
VAR _share = DIVIDE ( _rev, [Total Revenue] )
VAR _fmt   =
    IF ( _rev >= 10000000, "₹" & FORMAT ( _rev / 10000000, "#,##0.00" ) & " Cr",
    IF ( _rev >= 100000,   "₹" & FORMAT ( _rev / 100000,   "#,##0.00" ) & " L",
                           "₹" & FORMAT ( _rev, "#,##0" ) ) )
RETURN
    IF ( ISBLANK ( _name ), "No regional sales for the current selection.",
         _name & " is the top region with " & _fmt & " (" & FORMAT ( _share, "0.0%" ) & " of revenue)." )

Insight 3 - Category Profitability =
VAR _best   = [Top Profit Category]
VAR _low    = [Lowest Margin Category]
VAR _bestP  = CALCULATE ( [Total Profit], DimProduct[category] = _best )
VAR _lowM   = CALCULATE ( [Profit Margin], DimProduct[category] = _low )
VAR _lowP   = CALCULATE ( [Total Profit], DimProduct[category] = _low )
VAR _n      = COUNTROWS ( FILTER ( VALUES ( DimProduct[category] ), NOT ISBLANK ( [Total Revenue] ) ) )
VAR _bestFmt =
    IF ( _bestP < 0, "-", "" ) & "₹"
    & SWITCH ( TRUE (),
          ABS ( _bestP ) >= 10000000, FORMAT ( ABS ( _bestP ) / 10000000, "#,##0.00" ) & " Cr",
          ABS ( _bestP ) >= 100000,   FORMAT ( ABS ( _bestP ) / 100000,   "#,##0.00" ) & " L",
          FORMAT ( ABS ( _bestP ), "#,##0" ) )
RETURN
    IF ( ISBLANK ( _best ), "No category data for the current selection.",
         _best & " earns the most profit (" & _bestFmt & "). "
         & IF ( _n = 1,
                "It is the only category with sales in this selection.",
                IF ( _low = _best, "It also has the lowest margin at ", _low & " has the lowest margin at " )
                & FORMAT ( _lowM, "0.0%" )
                & IF ( _lowP < 0, " and is loss-making.", "." ) ) )

Insight 4 - Top Product =
VAR _name  = [Top Product]
VAR _rev   = CALCULATE ( [Total Revenue], DimProduct[product_name] = _name )
VAR _share = DIVIDE ( _rev, [Total Revenue] )
VAR _fmt   =
    IF ( _rev >= 10000000, "₹" & FORMAT ( _rev / 10000000, "#,##0.00" ) & " Cr",
    IF ( _rev >= 100000,   "₹" & FORMAT ( _rev / 100000,   "#,##0.00" ) & " L",
                           "₹" & FORMAT ( _rev, "#,##0" ) ) )
RETURN
    IF ( ISBLANK ( _name ), "No product sales for the current selection.",
         _name & " is the top product: " & _fmt & " (" & FORMAT ( _share, "0.0%" ) & " of revenue)." )

Insight 5 - Customer Concentration =
VAR _share = [Top 5 Customer Revenue Share]
RETURN
    IF ( ISBLANK ( _share ), "No customer sales for the current selection.",
         "The top 5 customers account for " & FORMAT ( _share, "0.0%" ) & " of revenue across "
         & FORMAT ( [Total Customers], "#,##0" ) & " active customers." )
```
Place each insight measure in its own card or text tile in the bottom-right panel. Nothing in them is typed in by hand.

---

## 7. Measure checklist against the brief

| Required measure | Defined as |
|---|---|
| Total Revenue / Cost / Profit | §1 |
| Total Orders / Total Customers | §1 |
| Profit Margin / Average Order Value | §1 |
| Previous Month Revenue / Profit | §2 (explicit month shift) |
| Revenue Growth % / Profit Growth % | §3 (uses the dynamic previous period) |
| Revenue by Selected Period | §5 |
| Revenue Share % | §5 |
| Product Rank / Customer Rank | §5 |

## 8. Edge cases the measures are designed for

| Situation | Behaviour |
|---|---|
| No slicers (24 months) | Growth cards show "–" because the prior 24 months are outside the data |
| First month of the data selected | Previous month is outside the calendar → "–" |
| January 2025 selected | Previous month is December 2024 (crosses the year boundary) |
| Empty selection | Revenue, profit, orders, customers and ratios are BLANK, cards show "–", ranks are BLANK, insights say "No … for the current selection." Growth and margin change are BLANK too, even when the prior period had sales (reference scenario **L**) |
| Prior revenue zero or blank | Growth is BLANK, never infinite |
| Negative profit | Passes through to cards, margin and colour rules; profit growth uses `ABS` of the base |
| Non-contiguous month selection (e.g. Jan + Mar) | each selected month is shifted individually (`TREATAS` on shifted `month_key`), so Jan + Mar 2025 is compared with Jan + Mar 2024; reference scenario **K** covers it |

## 9. Known limitations of these measures

- Not executed in Power BI Desktop; syntax and behaviour are unverified until you run them.
- The compact rupee text measures round at display precision, so a value just below a unit boundary (for example ₹99,999,999.70) can show as `₹1,000.00 L` instead of `₹10.00 Cr`. Full values are in tooltips.
- `Profit Growth %` divides by the absolute prior profit; if you prefer the conventional signed denominator, remove `ABS`.
