-- =====================================================================================
-- 02_data_quality_checks.sql
-- Purpose : prove the loaded tables obey the business rules. Every check returns the
--           number of VIOLATING rows, so the expected result for each line is 0.
-- Dialect : written in the portable subset of MySQL 8.0 / SQLite so the same file is run
--           by python/verify_sql_against_python.py (SQLite 3.45) as an executable test.
-- Run     : after 01_create_schema.sql.
-- =====================================================================================

-- @query: data_quality_violations
SELECT 'items_orphan_order' AS check_name, COUNT(*) AS violations
FROM order_items oi LEFT JOIN orders o ON o.order_id = oi.order_id
WHERE o.order_id IS NULL
UNION ALL
SELECT 'items_orphan_product', COUNT(*)
FROM order_items oi LEFT JOIN products p ON p.product_id = oi.product_id
WHERE p.product_id IS NULL
UNION ALL
SELECT 'orders_orphan_customer', COUNT(*)
FROM orders o LEFT JOIN customers c ON c.customer_id = o.customer_id
WHERE c.customer_id IS NULL
UNION ALL
SELECT 'orders_orphan_region', COUNT(*)
FROM orders o LEFT JOIN regions r ON r.region_id = o.region_id
WHERE r.region_id IS NULL
UNION ALL
SELECT 'customers_orphan_region', COUNT(*)
FROM customers c LEFT JOIN regions r ON r.region_id = c.home_region_id
WHERE r.region_id IS NULL
UNION ALL
SELECT 'orders_date_not_in_calendar', COUNT(*)
FROM orders o LEFT JOIN dim_date d ON d.full_date = o.order_date
WHERE d.full_date IS NULL
UNION ALL
SELECT 'orders_without_lines', COUNT(*)
FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.order_id)
UNION ALL
SELECT 'items_nonpositive_quantity', COUNT(*) FROM order_items WHERE quantity <= 0
UNION ALL
SELECT 'items_nonpositive_price', COUNT(*) FROM order_items WHERE unit_price <= 0
UNION ALL
SELECT 'items_nonpositive_cost', COUNT(*) FROM order_items WHERE unit_cost <= 0
UNION ALL
SELECT 'items_discount_out_of_range', COUNT(*) FROM order_items WHERE discount < 0 OR discount > 1
UNION ALL
SELECT 'items_same_product_twice_in_order', COUNT(*)
FROM (SELECT order_id, product_id FROM order_items GROUP BY order_id, product_id HAVING COUNT(*) > 1) dup
UNION ALL
SELECT 'orders_invalid_status', COUNT(*)
FROM orders WHERE order_status NOT IN ('Completed', 'Cancelled', 'Returned')
UNION ALL
SELECT 'orders_ship_before_order', COUNT(*)
FROM orders WHERE ship_date IS NOT NULL AND ship_date < order_date
UNION ALL
SELECT 'orders_cancelled_but_shipped', COUNT(*)
FROM orders WHERE order_status = 'Cancelled' AND ship_date IS NOT NULL
UNION ALL
SELECT 'customers_invalid_segment', COUNT(*)
FROM customers WHERE segment NOT IN ('Consumer', 'Corporate', 'Small Business', 'Unknown')
UNION ALL
SELECT 'dim_date_incomplete_months', COUNT(*)
FROM (SELECT month_key FROM dim_date
      GROUP BY month_key
      HAVING MIN(day_of_month) <> 1 OR MAX(day_of_month) <> COUNT(*)) bad_months
UNION ALL
SELECT 'dim_date_month_gaps', COUNT(*)
FROM (SELECT month_key - LAG(month_key) OVER (ORDER BY month_key) AS step
      FROM (SELECT DISTINCT month_key FROM dim_date) months) s
WHERE step IS NOT NULL AND step NOT IN (1, 89)      -- 89 = Dec -> Jan (e.g. 202501 - 202412)
ORDER BY check_name;

-- @query: table_row_counts
-- Informational: compare with the counts in data/README.md.
SELECT 'regions' AS table_name, COUNT(*) AS row_count FROM regions
UNION ALL SELECT 'products',    COUNT(*) FROM products
UNION ALL SELECT 'dim_date',    COUNT(*) FROM dim_date
UNION ALL SELECT 'customers',   COUNT(*) FROM customers
UNION ALL SELECT 'orders',      COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items;

-- @query: calendar_coverage
-- Informational: the calendar must cover at least 24 whole months with no gaps.
SELECT MIN(full_date) AS first_day, MAX(full_date) AS last_day,
       COUNT(DISTINCT month_key) AS months, COUNT(*) AS days
FROM dim_date;
