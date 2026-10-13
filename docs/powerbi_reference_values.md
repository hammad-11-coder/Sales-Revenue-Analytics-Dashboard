# Power BI reference values

Use these numbers to check the Power BI report once it is built (see `powerbi/PowerBI_Build_Guide.md`, step 12). They come from `python/generate_insights.py`, which reads the same processed CSVs and applies the same business rules as the DAX measures. All data is **synthetic**.

Set the slicers exactly as described, read the six KPI cards, and compare. Amounts are in rupees to the paisa; the cards will show compact `₹ Cr / ₹ L` forms of the same numbers. A difference of more than ₹0.01 means a measure, relationship or filter is wrong.

## KPI scenarios

| ID | Slicer selection | Revenue (₹) | Profit (₹) | Orders | Customers | Margin | AOV (₹) | Comparison | Prior revenue (₹) | Revenue growth | Profit growth | Margin change |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| A | No slicers (all 24 months) | 265,860,607.20 | 38,824,662.90 | 15,151 | 1,858 | 14.60% | 17,547.40 | n/a (blank) | – | n/a | n/a | – |
| B | Year = 2025 | 140,980,012.40 | 20,351,645.08 | 8,121 | 1,650 | 14.44% | 17,359.93 | vs same period last year | 124,880,594.80 | 12.89% | 10.17% | -0.36 pp |
| C | Year = 2024 | 124,880,594.80 | 18,473,017.82 | 7,030 | 1,334 | 14.79% | 17,763.95 | n/a (blank) | – | n/a | n/a | – |
| D | Year = 2025, Month = October | 15,632,250.05 | 2,098,400.08 | 921 | 576 | 13.42% | 16,973.13 | vs previous month | 14,161,366.95 | 10.39% | -2.62% | -1.79 pp |
| E | Year = 2024, Month = January | 10,803,773.15 | 1,610,110.99 | 508 | 332 | 14.90% | 21,267.27 | n/a (blank) | – | n/a | n/a | – |
| F | Year = 2025, Month = January (previous month is Dec 2024) | 8,397,626.00 | 1,344,702.86 | 548 | 367 | 16.01% | 15,324.14 | vs previous month | 11,497,311.55 | -26.96% | -25.31% | +0.35 pp |
| G | Year = 2025, Months = Jan-Jun | 59,546,283.60 | 8,789,468.07 | 3,524 | 1,150 | 14.76% | 16,897.36 | vs same period last year | 54,379,637.45 | 9.50% | 8.02% | -0.20 pp |
| H | Year = 2025, Region = West | 45,573,995.25 | 6,251,304.14 | 2,426 | 519 | 13.72% | 18,785.65 | vs same period last year | 44,028,056.35 | 3.51% | -7.60% | -1.65 pp |
| I | Year = 2025, Category = Furniture, Segment = Corporate | 17,224,394.55 | 224,929.40 | 842 | 316 | 1.31% | 20,456.53 | vs same period last year | 17,041,691.00 | 1.07% | -70.77% | -3.21 pp |
| J | Years = 2024 + 2025, Month = March (two Marches: prior period outside data) | 20,429,062.30 | 2,914,905.18 | 1,134 | 619 | 14.27% | 18,015.05 | n/a (blank) | – | n/a | n/a | – |
| K | Year = 2025, Months = Jan + Mar (non-contiguous: compared with Jan + Mar 2024 only) | 19,373,188.80 | 2,918,736.31 | 1,153 | 633 | 15.07% | 16,802.42 | vs same period last year | 20,257,272.65 | -4.36% | -1.09% | +0.50 pp |
| L | Year = 2025, Month = January, Region = Central, Category = Apparel, Segment = Small Business (EMPTY now, but December 2024 had sales: growth must be blank, not -100%) | 0.00 | 0.00 | 0 | 0 | n/a | – | vs previous month | 3,210.00 | n/a | n/a | – |

How to read the comparison columns: with exactly one month selected the card compares with the previous month; with any other period it compares with the same months one year earlier; if any prior month falls outside the Jan 2024 - Dec 2025 calendar the comparison is blank (`n/a`), never a partial figure.

**Empty-selection test:** `Region = Central, Category = Apparel, Segment = Corporate, Year = 2024, Month = Jan` has no completed sales. Cards must show blank (not an error, not 0%), charts must show no bars, and rankings must stay empty.

### Revenue and profit by region (all 24 months, no other slicers)

| Region | Revenue (₹) | Profit (₹) | Orders | Margin |
|---|---:|---:|---:|---:|
| West | 89,602,051.60 | 13,016,595.42 | 4,718 | 14.53% |
| South | 76,107,921.60 | 11,121,718.31 | 4,389 | 14.61% |
| North | 54,770,376.55 | 8,254,478.35 | 3,502 | 15.07% |
| Central | 22,831,906.55 | 3,216,490.37 | 1,131 | 14.09% |
| East | 22,548,350.90 | 3,215,380.45 | 1,411 | 14.26% |

### Revenue share and profit by category (all 24 months)

| Category | Revenue (₹) | Share | Profit (₹) | Margin |
|---|---:|---:|---:|---:|
| Technology | 167,589,715.60 | 63.04% | 22,481,099.07 | 13.41% |
| Furniture | 53,805,069.05 | 20.24% | 1,591,122.76 | 2.96% |
| Office Supplies | 16,090,937.65 | 6.05% | 4,294,529.65 | 26.69% |
| Apparel | 15,126,856.95 | 5.69% | 7,060,846.06 | 46.68% |
| Home & Kitchen | 13,248,027.95 | 4.98% | 3,397,065.36 | 25.64% |

### Top 10 products by revenue (all 24 months)

| Rank | Product | Revenue (₹) |
|---:|---|---:|
| 1 | Nexa Phone Pro 256GB | 34,981,566.90 |
| 2 | Aria Book Pro 16 | 26,624,075.40 |
| 3 | Aria Book 14 Laptop | 19,728,277.75 |
| 4 | Lumio Edge 5G | 19,256,933.50 |
| 5 | Veloce Air 13 Ultrabook | 17,968,490.60 |
| 6 | Zephyr Gaming Laptop | 14,620,480.00 |
| 7 | Conference Table 6-Seater | 10,624,687.80 |
| 8 | Visitor Chair Set of 2 | 10,179,630.50 |
| 9 | Orbit S20 Smartphone | 7,995,298.00 |
| 10 | Executive Leather Chair | 6,845,909.75 |

### Top 5 customers by revenue (all 24 months)

| Rank | Customer ID | Customer | Orders | Revenue (₹) | Profit (₹) |
|---:|---|---|---:|---:|---:|
| 1 | C0828 | Reyansh Siddiqui | 167 | 5,024,777.85 | 560,585.87 |
| 2 | C1674 | Kriti Desai | 90 | 4,118,808.85 | 521,008.42 |
| 3 | C2153 | Kavya Nair | 93 | 3,012,622.65 | 259,257.89 |
| 4 | C0386 | Aarav Mehta | 97 | 2,787,961.45 | 376,692.45 |
| 5 | C0569 | Ananya Verma | 50 | 2,612,440.15 | 410,462.39 |

### Monthly revenue and profit (all slicers cleared)

| Month | Revenue (₹) | Profit (₹) |
|---|---:|---:|
| Jan 2024 | 10,803,773.15 | 1,610,110.99 |
| Feb 2024 | 8,271,112.60 | 1,291,789.77 |
| Mar 2024 | 9,453,499.50 | 1,340,871.73 |
| Apr 2024 | 8,699,294.80 | 1,215,691.67 |
| May 2024 | 9,157,993.55 | 1,356,470.36 |
| Jun 2024 | 7,993,963.85 | 1,321,580.28 |
| Jul 2024 | 9,615,395.75 | 1,277,488.70 |
| Aug 2024 | 11,258,552.50 | 1,715,587.52 |
| Sep 2024 | 12,012,761.35 | 1,716,274.06 |
| Oct 2024 | 12,876,777.10 | 1,972,446.62 |
| Nov 2024 | 13,240,159.10 | 1,854,234.31 |
| Dec 2024 | 11,497,311.55 | 1,800,471.81 |
| Jan 2025 | 8,397,626.00 | 1,344,702.86 |
| Feb 2025 | 9,494,879.60 | 1,418,677.78 |
| Mar 2025 | 10,975,562.80 | 1,574,033.45 |
| Apr 2025 | 11,138,155.20 | 1,681,339.15 |
| May 2025 | 9,961,971.45 | 1,431,939.05 |
| Jun 2025 | 9,578,088.55 | 1,338,775.78 |
| Jul 2025 | 10,177,123.00 | 1,437,901.51 |
| Aug 2025 | 10,729,876.45 | 1,821,299.80 |
| Sep 2025 | 14,161,366.95 | 2,154,833.35 |
| Oct 2025 | 15,632,250.05 | 2,098,400.08 |
| Nov 2025 | 16,184,892.00 | 2,074,386.21 |
| Dec 2025 | 14,548,220.35 | 1,975,356.06 |
