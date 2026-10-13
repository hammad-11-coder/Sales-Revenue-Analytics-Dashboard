# Power BI build guide

> **Honest status.** A `.pbix` file was **not** created: Power BI Desktop is a Windows application and was not available where this
> project was authored, and no tool here can write a valid `.pbix`. Everything needed to build the report in about an hour *is*
> supplied and was prepared from verified data: cleaned CSVs, a data-model specification, DAX (written to match the SQL and Python logic that was tested, but not itself executed), a theme file, a canvas
> layout, and reference values to check your finished report against. Remaining manual work is listed in
> [Manual steps](#manual-steps-that-remain-yours).

All data is **synthetic**. Companion files: [`Data_Model.md`](Data_Model.md), [`DAX_Measures.md`](DAX_Measures.md),
[`theme.json`](theme.json), [`../docs/powerbi_reference_values.md`](../docs/powerbi_reference_values.md).
A working, filter-aware equivalent of this dashboard exists in [`../streamlit_app/app.py`](../streamlit_app/app.py) and a rendered
layout preview is in [`../dashboard_screenshots/`](../dashboard_screenshots/).

Requirements: Power BI Desktop (current version, Windows), the repository cloned locally. The processed CSVs are already in `data/processed/`; to regenerate them run `python python/generate_data.py && python python/clean_data.py`.

---

## 1. Start the report and apply the theme

1. New report → **View → Page view → Page size** → *Custom*: width **1280**, height **720** (16:9). Turn **Lock objects** on later once placed.
2. **View → Themes → Browse for themes** → `powerbi/theme.json`. This sets the categorical palette in a fixed, colour-blind-checked order (blue `#1D4ED8`, orange `#C2410C`, purple `#7C3AED`, green `#15803D`, pink `#DB2777`; validated with the dataviz palette validator), navy headings, rounded borders and a light-grey page.
3. **File → Options → Regional settings** → Locale for import *English (India)* so rupee currency formatting and lakh-style grouping follow Indian conventions where Power BI supports them.

## 2. Load data

**Get data → Text/CSV** for each of `fact_sales.csv`, `dim_date.csv`, `products.csv`, `customers.csv`, `regions.csv`. Use **Transform data** and apply the types and renames in [`Data_Model.md`](Data_Model.md#power-query-settings). Name the queries `FactSales`, `DimDate`, `DimProduct`, `DimCustomer`, `DimRegion`. Close & Apply.

## 3. Model

In Model view create the four relationships, mark `DimDate` as the date table, set the sort-by columns and hide key columns, exactly as in [`Data_Model.md`](Data_Model.md#relationships). Check that every relationship shows `*` → `1` and a single-direction arrow from the dimension.

## 4. Measures

Create an empty `_Measures` table (Home → Enter data → one column → name the table → Load, then hide the column). Paste every measure from [`DAX_Measures.md`](DAX_Measures.md), setting display folders and formats as described there. Do this *before* building visuals.

## 5. Canvas layout (1280 × 720 px)

Positions are X, Y, width, height in pixels (Format → General → Properties → Size/Position). 16 px outer margin, 8 px gutters.

| # | Element | Visual | X | Y | W | H |
|---|---|---|---:|---:|---:|---:|
| A | Title | Text box: **Sales & Revenue Analytics Dashboard** (navy, 22 pt semibold) | 16 | 6 | 700 | 34 |
| A | Subtitle | Text box: *Turning Retail Transaction Data into Business Insights* (grey, 11 pt) | 16 | 38 | 700 | 22 |
| A | Period & source | Card: `[Reporting Period]`, plus text *Source: synthetic retail transactions (generated, seed 42)* | 860 | 8 | 404 | 52 |
| C | Slicers (6) | Dropdown slicers: Year, Month, Region, Category, Product, Customer Segment | 16 + n×198 | 68 | 190 | 40 |
| C | Clear filters | Button → bookmark action (step 7) | 1204 | 68 | 60 | 40 |
| B | KPI cards (6) | Rounded rectangle + 3 texts (step 8) | 16 + n×209 | 116 | 203 | 78 |
| D | Revenue & profit trend | Line chart | 16 | 202 | 520 | 172 |
| E | Sales by region | Clustered bar | 544 | 202 | 330 | 172 |
| F | Sales by category | Donut | 882 | 202 | 382 | 172 |
| G | Top 10 products | Clustered bar (horizontal) | 16 | 382 | 420 | 180 |
| H | Profit by category | Clustered column or bar | 444 | 382 | 330 | 180 |
| I | Sales vs profit by month | Clustered column | 782 | 382 | 482 | 180 |
| J | Top 5 customers | Table | 16 | 570 | 620 | 142 |
| K | Key business insights | 5 card/text tiles stacked | 644 | 570 | 620 | 142 |

(n = 0…5 for the repeated elements; the 6 slicers at X = 16, 214, 412, 610, 808, 1006.)

Every chart: *Title on*, 12 pt navy; *Border* on, radius 8; *Visual header* off; alt text filled in (accessibility); tab order top-to-bottom, left-to-right.

## 6. Header (A)

Two text boxes and one card as in the table. The card's data source note is static text by design: it states that the data is synthetic, so nobody mistakes it for company performance.

## 7. Slicers and Clear filters (C)

- Year → `DimDate[cal_year]`; Month → `DimDate[month_name]` (sorted by `month_num`); Region → `DimRegion[region]`; Product Category → `DimProduct[category]`; Product → `DimProduct[product_name]` (turn the search box on); Customer Segment → `DimCustomer[segment]`.
- Style: *Dropdown*, multi-select with Ctrl, *Select all* option off, header text as the slicer name.
- **Clear filters**: with no slicer selection, **View → Bookmarks → Add**, name it *Reset*, and in the bookmark's options turn **Data** on and **Display/Current page** off. Insert a Button (*Back*-style or blank) and set *Action → Bookmark → Reset*. Because all slicers are cleared in the saved state, clicking resets them.
- *Edit interactions* is not needed for slicers: they filter every visual by default, which is the required behaviour.

## 8. KPI cards (B)

Per card build one rounded rectangle (white, 1 px `#E5E7EB` border, radius 10) containing:

| Layer | Content |
|---|---|
| label | text box with the KPI name, 10 pt grey |
| value | Card visual with the display or numeric measure, 22 pt navy semibold, label off |
| change | Card visual with the change-label measure; **Callout value → fx → Format by Field value →** the matching colour measure (green/red/grey) |
| comparison | Card visual with `[Comparison Label]`, 8 pt grey |

| KPI | Value measure | Change measure | Colour measure |
|---|---|---|---|
| Total Revenue | `[Total Revenue (Display)]` | `[Revenue Change Label]` | `[Revenue Change Color]` |
| Total Profit | `[Total Profit (Display)]` | `[Profit Change Label]` | `[Profit Change Color]` |
| Total Orders | `[Total Orders]` (format `#,##0`) | `[Orders Change Label]` | `[Orders Change Color]` |
| Total Customers | `[Total Customers]` (format `#,##0`) | `[Customers Change Label]` | `[Customers Change Color]` |
| Profit Margin | `[Profit Margin]` (format `0.0%`) | `[Margin Change Label]` | `[Margin Change Color]` |
| Average Order Value | `[Average Order Value (Display)]` | `[AOV Change Label]` | `[AOV Change Color]` |

All six `… Change Color` measures are defined in `DAX_Measures.md` §3. Each card also needs its previous-period value shown (brief requirement): add a fourth small text/card with `[Previous Period Revenue]` / `[Previous Period Profit]` / `[Previous Period Orders]` / `[Previous Period Customers]` / `[Previous Period Margin]` / `[Previous Period AOV]` formatted like the main value, captioned "Previous period". It is blank when there is no comparable period.

## 9. Charts

Use the theme's colours. Money axes use the `₹ Cr` number measures so units are consistent; tooltips show the full-rupee measures.

### D. Revenue & profit trend: Line chart
- X axis: `DimDate[month_label]` (sorted by `month_key`), *Type: Categorical*, *Concatenate labels* off.
- Y axis: `[Revenue (₹ Cr)]`, `[Profit (₹ Cr)]`; axis title "₹ crore"; no secondary axis, so both series share a unit.
- Tooltips: add `[Total Revenue]`, `[Total Profit]`, `[Profit Margin]`, `[Previous Month Revenue]`, `[Revenue Growth %]`.
- Optional year-over-year: add `[Revenue Same Period LY]` (÷ 10,000,000 in a copy of the measure) as a dashed grey line; January–December 2024 will be blank because 2023 is outside the data.
- Why no missing months: `DimDate` is a continuous calendar. Turn **Show items with no data** on for the X-axis field.

### E. Sales by region: Clustered bar
- Y axis `DimRegion[region]`, X axis `[Revenue (₹ Cr)]`; sort by revenue descending; data labels on (`0.00`).
- Bar colour: *fx → Format by Field value → `[Region Highlight Color]`*: green = strongest, orange = weakest, blue = others.

### F. Sales by category: Donut
- Legend `DimProduct[category]`, Values `[Total Revenue]`; detail labels: *Category, percent of total*.
- **Fixed category colours** (colour follows the entity, not its rank): Technology blue, Furniture orange, Office Supplies purple, Home & Kitchen green, Apparel pink. Set them under *Slices → Colors* so a filter never repaints the survivors.
- **Centre total:** Power BI donuts have no native centre label. Place a Card visual showing `[Total Revenue (Display)]` over the hole (send the card to front, background transparent, no border).

### G. Top 10 products by revenue: Horizontal bar
- Axis `DimProduct[product_name]`, Values `[Revenue (₹ Cr)]`; *Filters on this visual → product_name → Filter type: Top N → Top 10 → By value `[Total Revenue]`*; sort descending.
- Add `[Product Rank]` to the tooltip. The Top N filter is evaluated after slicers, so the list re-ranks under every selection.

### H. Profit by category: Clustered bar or column
- Axis `DimProduct[category]`, Values `[Profit (₹ Cr)]`; data labels on. Bar colour via *Format by Field value → `[Category Profit Color]`* (red = loss-making, orange = low margin, blue = otherwise).
- Do not fix the axis minimum at 0: let it go negative when a category loses money.

### I. Sales vs profit by month: Clustered column
- Axis `DimDate[month_label]`; Values `[Revenue (₹ Cr)]` (blue) and `[Profit (₹ Cr)]` (green); same unit and one axis; legend at top.

### J. Top 5 customers: Table
- Columns: `DimCustomer[customer_id]`, `DimCustomer[customer_name]`, `[Total Orders]`, `[Total Revenue]`, `[Total Profit]` (rupee format, 0 decimals).
- Visual filter: `customer_id` → Top N → **5** by `[Total Revenue]`. Optional rank column `[Customer Rank]` first.
- Turn off *Totals*; conditional font colour on `[Total Profit]` when negative.

### K. Key business insights
Five text/card tiles, each bound to one measure: `[Insight 1 - Revenue Trend]` … `[Insight 5 - Customer Concentration]`, 11 pt, word wrap on, small blue accent bar at the left. They are measures, so they change with every slicer.

## 10. Polish

- **Edit interactions:** the six slicers filter everything. Optionally set the donut and the region bar to *filter* the other charts so the report is explorable; leave the KPI cards on *none* for those two visuals to keep them stable.
- **Tooltips:** keep defaults plus the measures listed above, or build one tooltip page (320 × 200).
- **Formatting audit:** same font family (Segoe UI), 10 pt axis labels, gridlines light grey, no 3-D, no gradient fills, legends only where more than one series.
- **Accessibility:** alt text on every visual; do not rely on colour alone (value labels and the ▲ ▼ glyphs carry meaning).

## 11. Save and export

Save as `powerbi/Sales_Revenue_Analytics.pbix`. Export page images (**File → Export → Export to PDF**) or take screenshots at 100 % zoom and save them in `dashboard_screenshots/` as `powerbi_*.png`. Do not commit a `.pbix` that was built on real company data.

## 12. Validate before you call it finished

Compare your report with [`../docs/powerbi_reference_values.md`](../docs/powerbi_reference_values.md). Pass criteria: every revenue, profit, order and customer figure matches to the paisa and every growth cell matches after rounding: the card labels show growth with one decimal (`12.9%`) and margin change with two (`0.35 pp`), the reference file shows two decimals.

| Test | How | Expected |
|---|---|---|
| Totals | no slicers | scenario A |
| Comparison blank | Year 2024 only; then Year 2024 + Month Jan | cards show "–", comparison caption shows nothing |
| Year comparison | Year 2025 only | scenario B (+12.89 % revenue) |
| Month comparison | Year 2025 + Month October | scenario D (vs September) |
| Year boundary | Year 2025 + Month January | scenario F (previous month is December 2024) |
| Multi-month | Year 2025 + Jan–Jun | scenario G |
| Non-contiguous months | Year 2025 + Jan and Mar only | scenario K (compared with Jan + Mar 2024) |
| Combined filters | Year 2025 + West; Year 2025 + Furniture + Corporate | scenarios H, I |
| Empty selection | the Region/Category/Segment/Month combination named in the reference file | cards "–" (verify that Total Orders and Total Customers are blank too), no bars, no ranks, insights say "No … for the current selection", **no errors** |
| Rankings under filters | Region = East | Top 10 products and Top 5 customers change and equal the East-only ranking |
| Month ordering | scan trend and column charts | Jan 2024 → Dec 2025 left to right, 24 points, none missing |
| Negative profit | Category = Furniture, Year 2025, then watch Profit by category | bar turns orange/red when margin is low or negative |
| Consistency | sum of the region bars = sum of the category slices = revenue card | equal |

## Manual steps that remain yours

1. Build the `.pbix` by following steps 1–11 (no file is supplied).
2. Run the validation table in step 12; the DAX is unexecuted until you do.
3. Place the donut centre card, create the Reset bookmark and button, and set the Top N filters.
4. Replace the preview in `dashboard_screenshots/` with real Power BI screenshots and update the README image link if you wish.
