-- =====================================================================================
-- 03_transformations.sql
-- Purpose : build the reusable analytical layer as VIEWS on top of the base tables.
--           All business rules live here once; 04_business_analysis.sql only reads them.
-- Dialect : portable subset of MySQL 8.0 / SQLite (DROP VIEW IF EXISTS + CREATE VIEW,
--           no CREATE OR REPLACE) so python/verify_sql_against_python.py can execute it.
--
-- BUSINESS RULES (identical in Python, SQL and DAX; see docs/business_rules.md)
--   line_revenue = ROUND(quantity * unit_price * (1 - discount), 2)
--   line_cost    = ROUND(quantity * unit_cost, 2)
--   line_profit  = line_revenue - line_cost
--   An order is "placed" if it exists in orders (any status).
--   An order is "completed" if order_status = 'Completed'.
--   Revenue, cost, profit, order and customer counts, margin and AOV use COMPLETED orders only:
--     Cancelled = never shipped, Returned = refunded.
--
-- DOUBLE-COUNTING GUARD
--   orders (1) -> order_items (many). Joining the header to the lines repeats every header
--   attribute once per line, so header-level facts must be counted with COUNT(DISTINCT order_id)
--   or aggregated to ONE row per order first (vw_order_summary) before being averaged or joined on.
--   Dimension joins (products, customers, regions, dim_date) are many-to-one and cannot fan out.
-- =====================================================================================

DROP VIEW IF EXISTS vw_monthly_summary;
DROP VIEW IF EXISTS vw_customer_summary;
DROP VIEW IF EXISTS vw_order_summary;
DROP VIEW IF EXISTS vw_sales_detail;
DROP VIEW IF EXISTS vw_fact_sales;

-- ------------------------------------------------------------------------------------
-- vw_fact_sales : one row per order LINE, keys + measures only. Mirrors the Power BI fact table.
-- ------------------------------------------------------------------------------------
CREATE VIEW vw_fact_sales AS
SELECT
    oi.order_item_id,
    oi.order_id,
    o.order_date,
    o.ship_date,
    o.customer_id,
    oi.product_id,
    o.region_id,
    o.sales_channel,
    o.order_status,
    CASE WHEN o.order_status = 'Completed' THEN 1 ELSE 0 END               AS is_completed,
    oi.quantity,
    oi.unit_price,
    oi.unit_cost,
    oi.discount,
    ROUND(oi.quantity * oi.unit_price, 2)                                   AS gross_sales,
    ROUND(oi.quantity * oi.unit_price, 2)
      - ROUND(oi.quantity * oi.unit_price * (1 - oi.discount), 2)           AS discount_amount,
    ROUND(oi.quantity * oi.unit_price * (1 - oi.discount), 2)               AS line_revenue,
    ROUND(oi.quantity * oi.unit_cost, 2)                                    AS line_cost,
    ROUND(oi.quantity * oi.unit_price * (1 - oi.discount), 2)
      - ROUND(oi.quantity * oi.unit_cost, 2)                                AS line_profit,
    d.cal_year,
    d.cal_quarter,
    d.month_num,
    d.month_name,
    d.month_key,
    d.month_label
FROM order_items oi
JOIN orders   o ON o.order_id  = oi.order_id
JOIN dim_date d ON d.full_date = o.order_date;

-- ------------------------------------------------------------------------------------
-- vw_sales_detail : fact + descriptive attributes (many-to-one joins only -> no fan-out)
-- ------------------------------------------------------------------------------------
CREATE VIEW vw_sales_detail AS
SELECT
    f.*,
    p.product_name,
    p.category,
    p.subcategory,
    c.customer_name,
    c.segment,
    r.region,
    r.state,
    r.city
FROM vw_fact_sales f
JOIN products  p ON p.product_id  = f.product_id
JOIN customers c ON c.customer_id = f.customer_id
JOIN regions   r ON r.region_id   = f.region_id;

-- ------------------------------------------------------------------------------------
-- vw_order_summary : exactly ONE row per order (lines aggregated first, then joined to the header).
-- Use this view whenever you need an order-level value (AOV, basket size, per-customer order counts).
-- ------------------------------------------------------------------------------------
CREATE VIEW vw_order_summary AS
SELECT
    o.order_id,
    o.order_date,
    o.customer_id,
    o.region_id,
    o.sales_channel,
    o.order_status,
    t.line_count,
    t.units,
    t.gross_sales,
    t.order_revenue,
    t.order_cost,
    t.order_profit
FROM orders o
JOIN (SELECT order_id,
             COUNT(*)          AS line_count,
             SUM(quantity)     AS units,
             SUM(gross_sales)  AS gross_sales,
             SUM(line_revenue) AS order_revenue,
             SUM(line_cost)    AS order_cost,
             SUM(line_profit)  AS order_profit
      FROM vw_fact_sales
      GROUP BY order_id) t ON t.order_id = o.order_id;

-- ------------------------------------------------------------------------------------
-- vw_customer_summary : lifetime value per customer with at least one COMPLETED order.
-- Window functions assign a value quartile (1 = top 25% by revenue) and a frequency band.
-- ------------------------------------------------------------------------------------
CREATE VIEW vw_customer_summary AS
WITH per_customer AS (
    SELECT customer_id,
           COUNT(*)           AS completed_orders,
           SUM(order_revenue) AS revenue,
           SUM(order_profit)  AS profit,
           MIN(order_date)    AS first_order_date,
           MAX(order_date)    AS last_order_date
    FROM vw_order_summary
    WHERE order_status = 'Completed'
    GROUP BY customer_id
)
SELECT
    c.customer_id,
    c.customer_name,
    c.segment,
    p.completed_orders,
    p.revenue,
    p.profit,
    p.first_order_date,
    p.last_order_date,
    NTILE(4) OVER (ORDER BY p.revenue DESC)                                  AS value_quartile,
    CASE WHEN p.completed_orders = 1 THEN 'One-time'
         WHEN p.completed_orders <= 4 THEN 'Repeat (2-4)'
         ELSE 'Loyal (5+)' END                                               AS frequency_band
FROM customers c
JOIN per_customer p ON p.customer_id = c.customer_id;

-- ------------------------------------------------------------------------------------
-- vw_monthly_summary : one row per calendar month, INCLUDING months with no completed sales
-- (the calendar drives the rows, sales are LEFT JOINed), so a chart can never skip a month.
-- ------------------------------------------------------------------------------------
CREATE VIEW vw_monthly_summary AS
SELECT
    m.month_key,
    m.month_label,
    m.cal_year,
    m.month_num,
    COALESCE(ROUND(SUM(f.line_revenue), 2), 0)  AS revenue,
    COALESCE(ROUND(SUM(f.line_cost), 2), 0)     AS cost,
    COALESCE(ROUND(SUM(f.line_profit), 2), 0)   AS profit,
    COUNT(DISTINCT f.order_id)                  AS orders,
    COUNT(DISTINCT f.customer_id)               AS customers
FROM (SELECT DISTINCT month_key, month_label, cal_year, month_num FROM dim_date) m
LEFT JOIN vw_fact_sales f
       ON f.month_key = m.month_key AND f.is_completed = 1
GROUP BY m.month_key, m.month_label, m.cal_year, m.month_num;
