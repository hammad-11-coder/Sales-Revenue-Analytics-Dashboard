-- =====================================================================================
-- 04_business_analysis.sql
-- Purpose : the analytical queries behind every dashboard visual and KPI, written to show
--           explicit joins, CTEs, window functions (ROW_NUMBER, RANK, NTILE, LAG, running and
--           partitioned SUM) and double-count-safe aggregation.
-- Run     : after 03_transformations.sql. Each "-- @query:" block is an independent query.
-- Dialect : portable subset of MySQL 8.0 / SQLite. python/verify_sql_against_python.py runs
--           every block and reconciles the results with independently computed pandas figures.
-- Scope   : revenue / profit / orders / customers use COMPLETED orders only (see 03).
-- =====================================================================================

-- ------------------------------------------------------------------------------------
-- 1. Headline KPIs (the six KPI cards)
-- ------------------------------------------------------------------------------------
-- @query: kpi_summary
SELECT
    ROUND(SUM(line_revenue), 2)                                         AS revenue,
    ROUND(SUM(line_cost), 2)                                            AS cost,
    ROUND(SUM(line_profit), 2)                                          AS profit,
    COUNT(DISTINCT order_id)                                            AS orders,
    COUNT(DISTINCT customer_id)                                         AS customers,
    ROUND(100.0 * SUM(line_profit) / NULLIF(SUM(line_revenue), 0), 2)   AS margin_pct,
    ROUND(SUM(line_revenue) / NULLIF(COUNT(DISTINCT order_id), 0), 2)   AS aov
FROM vw_fact_sales
WHERE is_completed = 1;

-- ------------------------------------------------------------------------------------
-- 2. Order status mix: placed vs completed vs cancelled vs returned
-- ------------------------------------------------------------------------------------
-- @query: order_status_mix
SELECT
    order_status,
    COUNT(*)                                                             AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                   AS share_pct
FROM orders
GROUP BY order_status
ORDER BY orders DESC;

-- ------------------------------------------------------------------------------------
-- 3. Monthly revenue & profit trend with month-over-month change and year-to-date revenue
--    LAG gives the previous month; the calendar-driven view guarantees no missing months.
-- ------------------------------------------------------------------------------------
-- @query: monthly_trend
SELECT
    month_key,
    month_label,
    revenue,
    profit,
    LAG(revenue) OVER (ORDER BY month_key)                               AS prev_month_revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month_key))
          / NULLIF(LAG(revenue) OVER (ORDER BY month_key), 0), 2)        AS mom_revenue_growth_pct,
    ROUND(SUM(revenue) OVER (PARTITION BY cal_year ORDER BY month_num
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS ytd_revenue
FROM vw_monthly_summary
ORDER BY month_key;

-- ------------------------------------------------------------------------------------
-- NOTE: profit growth divides by ABS(previous profit), identical to the DAX and Python definitions
--       (docs/business_rules.md), so a loss that shrinks reads as an improvement.
-- 4. Year-over-year growth by month (self-join on the SAME month of the previous year,
--    so it stays correct even if a month were missing; LAG(,12) would silently shift).
-- ------------------------------------------------------------------------------------
-- @query: yoy_growth_monthly
SELECT
    cur.month_key,
    cur.month_label,
    cur.revenue                                                          AS revenue,
    prev.revenue                                                         AS prev_year_revenue,
    ROUND(100.0 * (cur.revenue - prev.revenue) / NULLIF(prev.revenue, 0), 2) AS yoy_revenue_growth_pct,
    cur.profit                                                           AS profit,
    prev.profit                                                          AS prev_year_profit,
    ROUND(100.0 * (cur.profit - prev.profit) / NULLIF(ABS(prev.profit), 0), 2)    AS yoy_profit_growth_pct
FROM vw_monthly_summary cur
LEFT JOIN vw_monthly_summary prev
       ON prev.cal_year = cur.cal_year - 1 AND prev.month_num = cur.month_num
ORDER BY cur.month_key;

-- ------------------------------------------------------------------------------------
-- 5. Yearly summary with YoY growth and margin
-- ------------------------------------------------------------------------------------
-- @query: yearly_summary
WITH yearly AS (
    SELECT cal_year,
           ROUND(SUM(line_revenue), 2)    AS revenue,
           ROUND(SUM(line_profit), 2)     AS profit,
           COUNT(DISTINCT order_id)       AS orders,
           COUNT(DISTINCT customer_id)    AS customers
    FROM vw_fact_sales
    WHERE is_completed = 1
    GROUP BY cal_year
)
SELECT
    cal_year,
    revenue,
    profit,
    orders,
    customers,
    ROUND(100.0 * profit / NULLIF(revenue, 0), 2)                                       AS margin_pct,
    ROUND(revenue / NULLIF(orders, 0), 2)                                               AS aov,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY cal_year))
          / NULLIF(LAG(revenue) OVER (ORDER BY cal_year), 0), 2)                        AS revenue_growth_pct,
    ROUND(100.0 * (profit - LAG(profit) OVER (ORDER BY cal_year))
          / NULLIF(ABS(LAG(profit) OVER (ORDER BY cal_year)), 0), 2)                         AS profit_growth_pct
FROM yearly
ORDER BY cal_year;

-- ------------------------------------------------------------------------------------
-- 6. Region performance (ranked bar chart): revenue, profit, margin, AOV, share and rank
--    AOV uses COUNT(DISTINCT order_id) so multi-line orders are not double counted.
-- ------------------------------------------------------------------------------------
-- @query: region_performance
SELECT
    region,
    ROUND(SUM(line_revenue), 2)                                          AS revenue,
    ROUND(SUM(line_profit), 2)                                           AS profit,
    ROUND(100.0 * SUM(line_profit) / NULLIF(SUM(line_revenue), 0), 2)    AS margin_pct,
    COUNT(DISTINCT order_id)                                             AS orders,
    ROUND(SUM(line_revenue) / NULLIF(COUNT(DISTINCT order_id), 0), 2)    AS aov,
    ROUND(100.0 * SUM(line_revenue) / SUM(SUM(line_revenue)) OVER (), 2) AS revenue_share_pct,
    RANK() OVER (ORDER BY SUM(line_revenue) DESC)                        AS revenue_rank
FROM vw_sales_detail
WHERE is_completed = 1
GROUP BY region
ORDER BY revenue_rank;

-- ------------------------------------------------------------------------------------
-- 7. Category performance: doughnut share, profit by category, margin
-- ------------------------------------------------------------------------------------
-- @query: category_performance
SELECT
    category,
    ROUND(SUM(line_revenue), 2)                                          AS revenue,
    ROUND(SUM(line_profit), 2)                                           AS profit,
    ROUND(100.0 * SUM(line_profit) / NULLIF(SUM(line_revenue), 0), 2)    AS margin_pct,
    ROUND(100.0 * SUM(line_revenue) / SUM(SUM(line_revenue)) OVER (), 2) AS revenue_share_pct,
    RANK() OVER (ORDER BY SUM(line_revenue) DESC)                        AS revenue_rank,
    RANK() OVER (ORDER BY SUM(line_profit) DESC)                         AS profit_rank
FROM vw_sales_detail
WHERE is_completed = 1
GROUP BY category
ORDER BY revenue_rank;

-- ------------------------------------------------------------------------------------
-- 8. Sub-category margin ranked WITHIN each category (PARTITION BY) - finds thin-margin lines
-- ------------------------------------------------------------------------------------
-- @query: subcategory_margin
SELECT
    category,
    subcategory,
    ROUND(SUM(line_revenue), 2)                                          AS revenue,
    ROUND(SUM(line_profit), 2)                                           AS profit,
    ROUND(100.0 * SUM(line_profit) / NULLIF(SUM(line_revenue), 0), 2)    AS margin_pct,
    RANK() OVER (PARTITION BY category
                 ORDER BY SUM(line_profit) / NULLIF(SUM(line_revenue), 0) DESC) AS margin_rank_in_category
FROM vw_sales_detail
WHERE is_completed = 1
GROUP BY category, subcategory
ORDER BY category, margin_rank_in_category;

-- ------------------------------------------------------------------------------------
-- 9. Margin by category and year, with the year-over-year change in percentage points
-- ------------------------------------------------------------------------------------
-- @query: category_margin_by_year
WITH cat_year AS (
    SELECT category, cal_year,
           SUM(line_revenue) AS revenue,
           SUM(line_profit)  AS profit
    FROM vw_sales_detail
    WHERE is_completed = 1
    GROUP BY category, cal_year
)
SELECT
    category,
    cal_year,
    ROUND(revenue, 2)                                                    AS revenue,
    ROUND(profit, 2)                                                     AS profit,
    ROUND(100.0 * profit / NULLIF(revenue, 0), 2)                        AS margin_pct,
    ROUND(100.0 * profit / NULLIF(revenue, 0)
          - LAG(100.0 * profit / NULLIF(revenue, 0)) OVER (PARTITION BY category ORDER BY cal_year), 2)
                                                                         AS margin_change_pp
FROM cat_year
ORDER BY category, cal_year;

-- ------------------------------------------------------------------------------------
-- 10. Top 10 products by revenue. RANK() keeps ties together; ROW_NUMBER() gives a stable tiebreak.
-- ------------------------------------------------------------------------------------
-- @query: top10_products
WITH product_sales AS (
    SELECT product_id, product_name, category,
           SUM(line_revenue) AS revenue,
           SUM(line_profit)  AS profit,
           SUM(quantity)     AS units
    FROM vw_sales_detail
    WHERE is_completed = 1
    GROUP BY product_id, product_name, category
),
ranked AS (
    SELECT product_id, product_name, category, revenue, profit, units,
           RANK()       OVER (ORDER BY revenue DESC)              AS revenue_rank,
           ROW_NUMBER() OVER (ORDER BY revenue DESC, product_id)  AS row_num
    FROM product_sales
)
SELECT revenue_rank, product_id, product_name, category,
       ROUND(revenue, 2) AS revenue, ROUND(profit, 2) AS profit, units
FROM ranked
WHERE row_num <= 10
ORDER BY row_num;

-- ------------------------------------------------------------------------------------
-- 11. Top 5 customers by revenue (order-level view first -> no double counting of orders)
-- ------------------------------------------------------------------------------------
-- @query: top5_customers
WITH ranked AS (
    SELECT customer_id, customer_name, segment, completed_orders, revenue, profit,
           RANK()       OVER (ORDER BY revenue DESC)               AS revenue_rank,
           ROW_NUMBER() OVER (ORDER BY revenue DESC, customer_id)  AS row_num
    FROM vw_customer_summary
)
SELECT revenue_rank, customer_id, customer_name, segment,
       completed_orders AS total_orders,
       ROUND(revenue, 2) AS total_revenue,
       ROUND(profit, 2)  AS total_profit
FROM ranked
WHERE row_num <= 5
ORDER BY row_num;

-- ------------------------------------------------------------------------------------
-- 12. Customer concentration: share of revenue from the top 5 customers and the top 10% of customers
-- ------------------------------------------------------------------------------------
-- @query: customer_concentration
WITH ranked AS (
    SELECT customer_id, revenue,
           ROW_NUMBER() OVER (ORDER BY revenue DESC, customer_id) AS row_num,
           COUNT(*)     OVER ()                                    AS n_customers,
           SUM(revenue) OVER ()                                    AS total_revenue
    FROM vw_customer_summary
)
SELECT
    MAX(n_customers)                                                              AS customers,
    ROUND(100.0 * SUM(CASE WHEN row_num <= 5 THEN revenue ELSE 0 END)
          / MAX(total_revenue), 2)                                                AS top5_share_pct,
    -- row_num is an integer, so "<= 10% of n" keeps FLOOR(0.10 * n) customers (no CAST needed)
    ROUND(100.0 * SUM(CASE WHEN row_num <= 0.10 * n_customers THEN revenue ELSE 0 END)
          / MAX(total_revenue), 2)                                                AS top10pct_share_pct
FROM ranked;

-- ------------------------------------------------------------------------------------
-- 13. Customer segmentation by value (NTILE quartiles) and by purchase frequency
-- ------------------------------------------------------------------------------------
-- @query: customer_value_tiers
SELECT
    value_quartile,
    COUNT(*)                                                             AS customers,
    ROUND(SUM(revenue), 2)                                               AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)           AS revenue_share_pct,
    ROUND(AVG(completed_orders), 2)                                      AS avg_orders_per_customer
FROM vw_customer_summary
GROUP BY value_quartile
ORDER BY value_quartile;

-- @query: customer_frequency_bands
SELECT
    frequency_band,
    COUNT(*)                                                             AS customers,
    ROUND(SUM(revenue), 2)                                               AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)           AS revenue_share_pct
FROM vw_customer_summary
GROUP BY frequency_band
ORDER BY customers DESC;

-- ------------------------------------------------------------------------------------
-- 14. Customer-segment performance (Consumer / Corporate / Small Business / Unknown)
-- ------------------------------------------------------------------------------------
-- @query: segment_performance
SELECT
    segment,
    ROUND(SUM(line_revenue), 2)                                          AS revenue,
    ROUND(SUM(line_profit), 2)                                           AS profit,
    ROUND(100.0 * SUM(line_profit) / NULLIF(SUM(line_revenue), 0), 2)    AS margin_pct,
    COUNT(DISTINCT order_id)                                             AS orders,
    COUNT(DISTINCT customer_id)                                          AS customers,
    ROUND(SUM(line_revenue) / NULLIF(COUNT(DISTINCT order_id), 0), 2)    AS aov
FROM vw_sales_detail
WHERE is_completed = 1
GROUP BY segment
ORDER BY revenue DESC;

-- ------------------------------------------------------------------------------------
-- 15. Average order value by year and sales channel, computed from ONE ROW PER ORDER
-- ------------------------------------------------------------------------------------
-- @query: aov_by_channel
SELECT
    s.sales_channel,
    COUNT(*)                         AS orders,
    ROUND(AVG(s.order_revenue), 2)   AS aov,
    ROUND(AVG(s.units), 2)           AS avg_units_per_order,
    ROUND(AVG(s.line_count), 2)      AS avg_lines_per_order
FROM vw_order_summary s
WHERE s.order_status = 'Completed'
GROUP BY s.sales_channel
ORDER BY aov DESC;

-- ------------------------------------------------------------------------------------
-- 16. Best-selling category in every month (ROW_NUMBER inside a partition)
-- ------------------------------------------------------------------------------------
-- @query: top_category_per_month
WITH month_cat AS (
    SELECT month_key, month_label, category, SUM(line_revenue) AS revenue
    FROM vw_sales_detail
    WHERE is_completed = 1
    GROUP BY month_key, month_label, category
),
ranked AS (
    SELECT month_key, month_label, category, revenue,
           ROW_NUMBER() OVER (PARTITION BY month_key ORDER BY revenue DESC, category) AS rn
    FROM month_cat
)
SELECT month_key, month_label, category AS top_category, ROUND(revenue, 2) AS revenue
FROM ranked
WHERE rn = 1
ORDER BY month_key;

-- ------------------------------------------------------------------------------------
-- 17. Placed vs completed orders and cancellation / return rates
-- ------------------------------------------------------------------------------------
-- @query: placed_vs_completed
SELECT
    COUNT(*)                                                             AS placed_orders,
    SUM(CASE WHEN order_status = 'Completed' THEN 1 ELSE 0 END)          AS completed_orders,
    SUM(CASE WHEN order_status = 'Cancelled' THEN 1 ELSE 0 END)          AS cancelled_orders,
    SUM(CASE WHEN order_status = 'Returned'  THEN 1 ELSE 0 END)          AS returned_orders,
    ROUND(100.0 * SUM(CASE WHEN order_status = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN order_status = 'Returned'  THEN 1 ELSE 0 END) / COUNT(*), 2) AS return_rate_pct
FROM orders;

-- ------------------------------------------------------------------------------------
-- 18. Double-counting guard: lines vs distinct orders after the header-to-lines join
--     (COUNT(*) here would overstate "orders" by the average lines-per-order factor)
-- ------------------------------------------------------------------------------------
-- @query: double_count_guard
SELECT
    COUNT(*)                  AS completed_lines,
    COUNT(DISTINCT order_id)  AS completed_orders,
    ROUND(1.0 * COUNT(*) / COUNT(DISTINCT order_id), 3) AS lines_per_order
FROM vw_fact_sales
WHERE is_completed = 1;

-- ------------------------------------------------------------------------------------
-- 19. Reconciliation checks: every row must say OK
-- ------------------------------------------------------------------------------------
-- @query: reconciliation_checks
SELECT 'view_lines_equal_table_lines' AS check_name,
       CASE WHEN (SELECT COUNT(*) FROM vw_fact_sales) = (SELECT COUNT(*) FROM order_items)
            THEN 'OK' ELSE 'FAIL' END AS result
UNION ALL
SELECT 'revenue_view_equals_recomputed_from_lines',
       CASE WHEN ABS((SELECT SUM(line_revenue) FROM vw_fact_sales WHERE is_completed = 1)
                   - (SELECT SUM(ROUND(oi.quantity * oi.unit_price * (1 - oi.discount), 2))
                      FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
                      WHERE o.order_status = 'Completed')) < 0.01
            THEN 'OK' ELSE 'FAIL' END
UNION ALL
SELECT 'profit_equals_revenue_minus_cost',
       CASE WHEN ABS((SELECT SUM(line_profit) FROM vw_fact_sales WHERE is_completed = 1)
                   - ((SELECT SUM(line_revenue) FROM vw_fact_sales WHERE is_completed = 1)
                    - (SELECT SUM(line_cost)    FROM vw_fact_sales WHERE is_completed = 1))) < 0.01
            THEN 'OK' ELSE 'FAIL' END
UNION ALL
SELECT 'monthly_view_sums_to_total_revenue',
       CASE WHEN ABS((SELECT SUM(revenue) FROM vw_monthly_summary)
                   - (SELECT SUM(line_revenue) FROM vw_fact_sales WHERE is_completed = 1)) < 0.01
            THEN 'OK' ELSE 'FAIL' END
UNION ALL
SELECT 'region_breakdown_sums_to_total_revenue',
       CASE WHEN ABS((SELECT SUM(line_revenue) FROM vw_sales_detail WHERE is_completed = 1)
                   - (SELECT SUM(line_revenue) FROM vw_fact_sales   WHERE is_completed = 1)) < 0.01
            THEN 'OK' ELSE 'FAIL' END
UNION ALL
SELECT 'order_summary_has_one_row_per_order',
       CASE WHEN (SELECT COUNT(*) FROM vw_order_summary) = (SELECT COUNT(*) FROM orders)
            THEN 'OK' ELSE 'FAIL' END
UNION ALL
SELECT 'customer_summary_revenue_equals_total_revenue',
       CASE WHEN ABS((SELECT SUM(revenue) FROM vw_customer_summary)
                   - (SELECT SUM(line_revenue) FROM vw_fact_sales WHERE is_completed = 1)) < 0.01
            THEN 'OK' ELSE 'FAIL' END;
