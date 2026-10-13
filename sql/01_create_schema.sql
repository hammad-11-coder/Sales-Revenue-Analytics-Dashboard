-- =====================================================================================
-- 01_create_schema.sql        MySQL 8.0 (8.0.16+ needed for CHECK constraints to be enforced)
-- Purpose : create the sales_analytics database, tables, keys, constraints and load the
--           cleaned CSVs from data/processed/.
-- Data    : 100% SYNTHETIC. See data/README.md.
-- Run     : mysql --local-infile=1 -u <user> -p < sql/01_create_schema.sql
--           (or paste into MySQL Workbench; edit the file paths in the LOAD DATA statements of SECTION B first)
-- STATUS  : written for MySQL 8.0. This script was NOT executed in the authoring
--           environment (no MySQL server available there). The analysis scripts 02-04
--           were executed against SQLite using the same CSVs; see
--           python/verify_sql_against_python.py.
-- =====================================================================================

-- ------------------------------------------------------------------ SECTION A: schema
CREATE DATABASE IF NOT EXISTS sales_analytics
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE sales_analytics;

SET FOREIGN_KEY_CHECKS = 0;
DROP VIEW  IF EXISTS vw_monthly_summary;
DROP VIEW  IF EXISTS vw_customer_summary;
DROP VIEW  IF EXISTS vw_order_summary;
DROP VIEW  IF EXISTS vw_sales_detail;
DROP VIEW  IF EXISTS vw_fact_sales;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS regions;
DROP TABLE IF EXISTS dim_date;
SET FOREIGN_KEY_CHECKS = 1;

-- Dimension: calendar (one row per day; continuous, no gaps).
-- NOTE: YEAR_MONTH is a reserved word in MySQL, so the year-month fields are month_key / month_label.
CREATE TABLE dim_date (
    date_key         INT          NOT NULL,            -- yyyymmdd
    full_date        DATE         NOT NULL,
    cal_year         SMALLINT     NOT NULL,
    quarter_num      TINYINT      NOT NULL,
    cal_quarter      CHAR(2)      NOT NULL,            -- Q1..Q4
    year_quarter     CHAR(7)      NOT NULL,            -- 2025-Q3
    month_num        TINYINT      NOT NULL,
    month_name       VARCHAR(10)  NOT NULL,
    month_short      CHAR(3)      NOT NULL,
    month_key        INT          NOT NULL,            -- yyyymm, sorts chronologically
    month_label      VARCHAR(8)   NOT NULL,            -- 'Jan 2025' (sort by month_key)
    day_of_month     TINYINT      NOT NULL,
    week_of_year     TINYINT      NOT NULL,
    day_of_week_num  TINYINT      NOT NULL,            -- Monday = 1
    day_name         VARCHAR(10)  NOT NULL,
    is_weekend       TINYINT      NOT NULL,
    PRIMARY KEY (date_key),
    UNIQUE KEY uq_dim_date_full_date (full_date),
    KEY ix_dim_date_month_key (month_key)
) ENGINE = InnoDB;

CREATE TABLE regions (
    region_id  INT          NOT NULL,
    region     VARCHAR(20)  NOT NULL,
    state      VARCHAR(40)  NOT NULL,
    city       VARCHAR(40)  NOT NULL,
    PRIMARY KEY (region_id),
    UNIQUE KEY uq_regions_state_city (state, city)
) ENGINE = InnoDB;

CREATE TABLE products (
    product_id    VARCHAR(10)   NOT NULL,
    product_name  VARCHAR(80)   NOT NULL,
    category      VARCHAR(30)   NOT NULL,
    subcategory   VARCHAR(30)   NOT NULL,
    unit_price    DECIMAL(12,2) NOT NULL,              -- list price (INR)
    unit_cost     DECIMAL(12,2) NOT NULL,              -- standard cost (INR)
    PRIMARY KEY (product_id),
    CONSTRAINT ck_products_price CHECK (unit_price > 0),
    CONSTRAINT ck_products_cost  CHECK (unit_cost > 0)
) ENGINE = InnoDB;

CREATE TABLE customers (
    customer_id     VARCHAR(10)  NOT NULL,
    customer_name   VARCHAR(80)  NOT NULL,             -- synthetic, fictional
    segment         VARCHAR(20)  NOT NULL,
    home_region_id  INT          NOT NULL,
    signup_date     DATE         NOT NULL,
    PRIMARY KEY (customer_id),
    CONSTRAINT fk_customers_region FOREIGN KEY (home_region_id) REFERENCES regions (region_id),
    CONSTRAINT ck_customers_segment CHECK (segment IN ('Consumer', 'Corporate', 'Small Business', 'Unknown'))
) ENGINE = InnoDB;

CREATE TABLE orders (
    order_id       VARCHAR(20)  NOT NULL,
    order_date     DATE         NOT NULL,
    ship_date      DATE         NULL,                  -- NULL for cancelled orders / unreliable source values
    customer_id    VARCHAR(10)  NOT NULL,
    region_id      INT          NOT NULL,              -- ship-to region (drives regional reporting)
    sales_channel  VARCHAR(20)  NOT NULL,
    order_status   VARCHAR(10)  NOT NULL,
    PRIMARY KEY (order_id),
    KEY ix_orders_order_date (order_date),
    KEY ix_orders_customer (customer_id),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
    CONSTRAINT fk_orders_region   FOREIGN KEY (region_id)   REFERENCES regions (region_id),
    CONSTRAINT fk_orders_date     FOREIGN KEY (order_date)  REFERENCES dim_date (full_date),
    CONSTRAINT ck_orders_status   CHECK (order_status IN ('Completed', 'Cancelled', 'Returned')),
    CONSTRAINT ck_orders_ship     CHECK (ship_date IS NULL OR ship_date >= order_date)
) ENGINE = InnoDB;

CREATE TABLE order_items (
    order_item_id  INT           NOT NULL,
    order_id       VARCHAR(20)   NOT NULL,
    product_id     VARCHAR(10)   NOT NULL,
    quantity       INT           NOT NULL,
    unit_price     DECIMAL(12,2) NOT NULL,             -- price actually charged per unit (INR)
    unit_cost      DECIMAL(12,2) NOT NULL,
    discount       DECIMAL(5,4)  NOT NULL,             -- fraction: 0.15 = 15% off
    PRIMARY KEY (order_item_id),
    KEY ix_items_order (order_id),
    KEY ix_items_product (product_id),
    CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders (order_id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products (product_id),
    CONSTRAINT ck_items_qty      CHECK (quantity > 0),
    CONSTRAINT ck_items_price    CHECK (unit_price > 0),
    CONSTRAINT ck_items_cost     CHECK (unit_cost > 0),
    CONSTRAINT ck_items_discount CHECK (discount BETWEEN 0 AND 1)
) ENGINE = InnoDB;

-- ------------------------------------------------------------------ SECTION B: load the cleaned CSVs
-- 1. Find/replace /ABSOLUTE/PATH/TO/sales-revenue-analytics in the six statements below with
--    your clone's path (forward slashes, even on Windows). MySQL cannot take the file name
--    from a variable, so the literal has to be edited in each statement.
-- 2. LOCAL INFILE must be allowed on both sides:  SET GLOBAL local_infile = 1;  and  mysql --local-infile=1
-- 3. If rows load with a trailing carriage return (CSV saved with Windows line endings),
--    change LINES TERMINATED BY '\n' to '\r\n'.
-- Alternative with no path editing: MySQL Workbench -> right-click table -> Table Data Import Wizard.
LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/regions.csv'
INTO TABLE regions FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (region_id, region, state, city);

LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/products.csv'
INTO TABLE products FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (product_id, product_name, category, subcategory, unit_price, unit_cost);

LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/dim_date.csv'
INTO TABLE dim_date FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (full_date, date_key, cal_year, quarter_num, cal_quarter, year_quarter, month_num, month_name,
                month_short, month_key, month_label, day_of_month, week_of_year, day_of_week_num, day_name, is_weekend);

LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/customers.csv'
INTO TABLE customers FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (customer_id, customer_name, segment, home_region_id, signup_date);

-- ship_date is blank for cancelled orders; convert '' to NULL.
LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/orders.csv'
INTO TABLE orders FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (order_id, order_date, @ship_date, customer_id, region_id, sales_channel, order_status)
SET ship_date = NULLIF(@ship_date, '');

LOAD DATA LOCAL INFILE '/ABSOLUTE/PATH/TO/sales-revenue-analytics/data/processed/order_items.csv'
INTO TABLE order_items FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n'
IGNORE 1 LINES (order_item_id, order_id, product_id, quantity, unit_price, unit_cost, discount);

-- ------------------------------------------------------------------ SECTION C: load check
-- Expected row counts for the seed-42 dataset are listed in data/README.md.
SELECT 'regions' AS table_name, COUNT(*) AS row_count FROM regions
UNION ALL SELECT 'products',    COUNT(*) FROM products
UNION ALL SELECT 'dim_date',    COUNT(*) FROM dim_date
UNION ALL SELECT 'customers',   COUNT(*) FROM customers
UNION ALL SELECT 'orders',      COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items;
