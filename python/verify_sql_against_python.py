#!/usr/bin/env python3
"""Run the project's SQL against the processed CSVs and reconcile it with independent pandas results.

What this proves
----------------
* sql/03_transformations.sql, sql/02_data_quality_checks.sql and every query in
  sql/04_business_analysis.sql EXECUTE without error and return the documented results.
* The numbers they return equal figures computed separately in pandas straight from the
  six base tables (not from fact_sales.csv and not through kpi_definitions.py).

What it does NOT prove
----------------------
The engine used here is SQLite (bundled with Python), because no MySQL server is available
in many environments. Files 02-04 are deliberately written in the SQL subset common to
MySQL 8.0 and SQLite (CTEs, window functions, explicit joins, no engine-specific functions),
but sql/01_create_schema.sql (DDL, constraints, LOAD DATA) is MySQL-only and is NOT executed
here. Run files 01-04 on a real MySQL 8.0 server to complete verification on that engine.

Usage:
    python python/verify_sql_against_python.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
TOL = 0.011  # one paisa of rounding slack on rupee amounts


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


# ----------------------------------------------------------------------------- SQL plumbing
def split_statements(sql_text: str) -> list[str]:
    """Split a script into statements (comments stripped; no semicolons appear inside string literals)."""
    no_comments = "\n".join(re.sub(r"--.*$", "", line) for line in sql_text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def named_queries(sql_text: str) -> dict[str, str]:
    """Return {name: sql} for every '-- @query: name' block."""
    out: dict[str, str] = {}
    parts = re.split(r"^-- @query:\s*(\w+)\s*$", sql_text, flags=re.MULTILINE)
    for name, body in zip(parts[1::2], parts[2::2]):
        stmts = split_statements(body)
        if len(stmts) != 1:
            raise ValueError(f"query block '{name}' must contain exactly one statement, found {len(stmts)}")
        out[name] = stmts[0]
    return out


def load_sqlite(processed: Path) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    for name in ("regions", "products", "customers", "orders", "order_items", "dim_date"):
        pd.read_csv(processed / f"{name}.csv").to_sql(name, con, index=False)
    return con


# ----------------------------------------------------------------------------- independent pandas model
def pandas_model(processed: Path) -> pd.DataFrame:
    """Completed-order lines joined to every dimension, built independently of kpi_definitions."""
    items = pd.read_csv(processed / "order_items.csv")
    orders = pd.read_csv(processed / "orders.csv")
    prods = pd.read_csv(processed / "products.csv")
    custs = pd.read_csv(processed / "customers.csv")
    regs = pd.read_csv(processed / "regions.csv")
    dates = pd.read_csv(processed / "dim_date.csv")
    df = (items.merge(orders, on="order_id")
          .merge(prods[["product_id", "product_name", "category", "subcategory"]], on="product_id")
          .merge(custs[["customer_id", "customer_name", "segment"]], on="customer_id")
          .merge(regs[["region_id", "region"]], on="region_id")
          .merge(dates[["full_date", "cal_year", "month_num", "month_key"]], left_on="order_date", right_on="full_date"))
    df["rev"] = (df.quantity * df.unit_price * (1 - df.discount)).round(2)
    df["cost"] = (df.quantity * df.unit_cost).round(2)
    df["profit"] = df.rev - df.cost
    return df


def _close(a, b, tol=TOL) -> bool:
    return bool(np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), atol=tol, rtol=0, equal_nan=True))


def compare(name: str, sql_df: pd.DataFrame, py_df: pd.DataFrame, keys: list[str], cols: list[str],
            tol: float = TOL) -> Result:
    a = sql_df.sort_values(keys).reset_index(drop=True)
    b = py_df.sort_values(keys).reset_index(drop=True)
    if len(a) != len(b):
        return Result(name, False, f"row count SQL={len(a)} pandas={len(b)}")
    for k in keys:
        if not (a[k].astype(str).to_numpy() == b[k].astype(str).to_numpy()).all():
            return Result(name, False, f"key column '{k}' differs")
    bad = [c for c in cols if not _close(a[c].astype(float), b[c].astype(float), tol)]
    return Result(name, not bad, f"{len(a)} rows; mismatched columns: {bad}" if bad else f"{len(a)} rows match")


# ----------------------------------------------------------------------------- the run
def run(processed: Path | None = None, sql_dir: Path | None = None) -> list[Result]:
    processed = processed or REPO_ROOT / "data" / "processed"
    sql_dir = sql_dir or REPO_ROOT / "sql"
    results: list[Result] = []
    con = load_sqlite(processed)

    # 03: create the views
    stmts = split_statements((sql_dir / "03_transformations.sql").read_text())
    try:
        for s in stmts:
            con.execute(s)
        results.append(Result("03_transformations.sql executes", True, f"{len(stmts)} statements"))
    except Exception as e:  # noqa: BLE001
        results.append(Result("03_transformations.sql executes", False, repr(e)))
        return results

    def q(file: str, name: str) -> pd.DataFrame:
        return pd.read_sql_query(named_queries((sql_dir / file).read_text())[name], con)

    # every named query must execute
    for file in ("02_data_quality_checks.sql", "04_business_analysis.sql"):
        for qname, sql in named_queries((sql_dir / file).read_text()).items():
            try:
                n = len(pd.read_sql_query(sql, con))
                results.append(Result(f"{file}:{qname} executes", True, f"{n} rows"))
            except Exception as e:  # noqa: BLE001
                results.append(Result(f"{file}:{qname} executes", False, repr(e)))

    m = pandas_model(processed)
    done = m[m.order_status == "Completed"]

    # 02: data-quality violations all zero
    dq = q("02_data_quality_checks.sql", "data_quality_violations")
    results.append(Result("02 data-quality violations are all zero", bool((dq.violations == 0).all()),
                          f"{len(dq)} checks; non-zero: {dq[dq.violations != 0].to_dict('records')}"))

    # 04 reconciliation block
    rc = q("04_business_analysis.sql", "reconciliation_checks")
    results.append(Result("04 reconciliation checks all OK", bool((rc.result == "OK").all()),
                          f"{len(rc)} checks; failing: {rc[rc.result != 'OK'].check_name.tolist()}"))

    # 1. headline KPIs
    k = q("04_business_analysis.sql", "kpi_summary").iloc[0]
    rev, cost = done.rev.sum(), done.cost.sum()
    exp = {"revenue": rev, "cost": cost, "profit": rev - cost, "orders": done.order_id.nunique(),
           "customers": done.customer_id.nunique(), "margin_pct": 100 * (rev - cost) / rev,
           "aov": rev / done.order_id.nunique()}
    bad = [c for c, v in exp.items() if not _close(k[c], v, 0.011 if c != "orders" and c != "customers" else 0)]
    results.append(Result("kpi_summary = pandas", not bad, f"mismatched: {bad}" if bad else
                          f"revenue={k['revenue']:,.2f} profit={k['profit']:,.2f} orders={int(k['orders']):,}"))

    # 2. order-status mix
    st = q("04_business_analysis.sql", "order_status_mix")
    exp_st = (pd.read_csv(processed / "orders.csv").groupby("order_status").size().rename("orders").reset_index())
    results.append(compare("order_status_mix = pandas", st[["order_status", "orders"]], exp_st, ["order_status"], ["orders"], 0))

    # 3. monthly trend
    mt = q("04_business_analysis.sql", "monthly_trend")
    exp_m = done.groupby("month_key").agg(revenue=("rev", "sum"), profit=("profit", "sum")).reset_index()
    results.append(compare("monthly_trend revenue/profit = pandas", mt[["month_key", "revenue", "profit"]],
                           exp_m, ["month_key"], ["revenue", "profit"]))
    exp_m = exp_m.sort_values("month_key").reset_index(drop=True)
    exp_m["mom"] = 100 * exp_m.revenue.pct_change()
    results.append(Result("monthly_trend MoM growth = pandas pct_change",
                          _close(mt.sort_values("month_key").mom_revenue_growth_pct.astype(float), exp_m.mom, 0.011),
                          f"{len(mt)} months, first month MoM is NULL"))
    exp_m["year"] = exp_m.month_key // 100
    exp_m["ytd"] = exp_m.groupby("year").revenue.cumsum()
    results.append(Result("monthly_trend YTD running total = pandas cumsum",
                          _close(mt.sort_values("month_key").ytd_revenue, exp_m.ytd), ""))
    results.append(Result("monthly_trend has 24 consecutive months (no gaps)", len(mt) == 24 and mt.month_key.is_monotonic_increasing,
                          f"{len(mt)} rows"))

    # 4. YoY by month
    yy = q("04_business_analysis.sql", "yoy_growth_monthly").sort_values("month_key").reset_index(drop=True)
    piv = exp_m.set_index("month_key").revenue
    exp_yoy = pd.Series({mk: (100 * (piv[mk] / piv[mk - 100] - 1) if (mk - 100) in piv.index else np.nan)
                         for mk in piv.index}).sort_index()
    results.append(Result("yoy_growth_monthly = pandas (NULL for first-year months)",
                          _close(yy.yoy_revenue_growth_pct.astype(float), exp_yoy.to_numpy(), 0.011), ""))

    # 5. yearly summary
    ys = q("04_business_analysis.sql", "yearly_summary")
    exp_y = done.assign(y=done.month_key // 100).groupby("y").agg(
        revenue=("rev", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
        customers=("customer_id", "nunique")).reset_index().rename(columns={"y": "cal_year"})
    results.append(compare("yearly_summary = pandas", ys[["cal_year", "revenue", "profit", "orders", "customers"]],
                           exp_y, ["cal_year"], ["revenue", "profit", "orders", "customers"]))
    g25 = 100 * (exp_y.revenue.iloc[1] / exp_y.revenue.iloc[0] - 1)
    results.append(Result("yearly_summary revenue growth 2025 vs 2024 = pandas",
                          _close([ys.revenue_growth_pct.iloc[1]], [g25], 0.011), f"{g25:.2f}%"))

    # 6. region / 7. category / 14. segment
    for qname, col, extra in [("region_performance", "region", True), ("category_performance", "category", True),
                              ("segment_performance", "segment", False)]:
        sq = q("04_business_analysis.sql", qname)
        ex = done.groupby(col).agg(revenue=("rev", "sum"), profit=("profit", "sum"),
                                   orders=("order_id", "nunique")).reset_index()
        ex["margin_pct"] = 100 * ex.profit / ex.revenue
        ex["aov"] = ex.revenue / ex.orders
        cols = ["revenue", "profit", "orders", "margin_pct", "aov"] if qname != "category_performance" else \
            ["revenue", "profit", "margin_pct"]
        sub = [col] + [c for c in cols]
        results.append(compare(f"{qname} = pandas", sq[sub], ex[sub], [col], cols))
        if extra:
            share = 100 * ex.set_index(col).revenue / ex.revenue.sum()
            results.append(Result(f"{qname} revenue_share_pct sums to 100 and matches",
                                  abs(sq.revenue_share_pct.sum() - 100) < 0.05 and
                                  _close(sq.set_index(col).revenue_share_pct.sort_index(), share.sort_index(), 0.011), ""))
            top = ex.sort_values("revenue", ascending=False)[col].iloc[0]
            results.append(Result(f"{qname} rank 1 is the highest-revenue {col}",
                                  sq.sort_values("revenue_rank")[col].iloc[0] == top, str(top)))

    # 9. category margin by year
    cm = q("04_business_analysis.sql", "category_margin_by_year")
    exp_cm = done.assign(y=done.month_key // 100).groupby(["category", "y"]).agg(
        revenue=("rev", "sum"), profit=("profit", "sum")).reset_index().rename(columns={"y": "cal_year"})
    exp_cm["margin_pct"] = 100 * exp_cm.profit / exp_cm.revenue
    cm["cal_year"] = cm.cal_year.astype(int)
    results.append(compare("category_margin_by_year = pandas",
                           cm.assign(k=cm.category + "|" + cm.cal_year.astype(str))[["k", "revenue", "profit", "margin_pct"]],
                           exp_cm.assign(k=exp_cm.category + "|" + exp_cm.cal_year.astype(str))[["k", "revenue", "profit", "margin_pct"]],
                           ["k"], ["revenue", "profit", "margin_pct"]))

    # 10. top-10 products
    t10 = q("04_business_analysis.sql", "top10_products")
    ex10 = done.groupby(["product_id", "product_name"]).agg(revenue=("rev", "sum"), profit=("profit", "sum")) \
        .reset_index().sort_values(["revenue", "product_id"], ascending=[False, True]).head(10)
    ok = list(t10.product_id) == list(ex10.product_id) and _close(t10.revenue, ex10.revenue)
    results.append(Result("top10_products ids, order and revenue = pandas", ok, ", ".join(t10.product_name.head(3)) + " ..."))

    # 11. top-5 customers
    t5 = q("04_business_analysis.sql", "top5_customers")
    ex5 = done.groupby(["customer_id", "customer_name"]).agg(
        revenue=("rev", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique")).reset_index() \
        .sort_values(["revenue", "customer_id"], ascending=[False, True]).head(5)
    ok = (list(t5.customer_id) == list(ex5.customer_id) and _close(t5.total_revenue, ex5.revenue)
          and _close(t5.total_profit, ex5.profit) and _close(t5.total_orders, ex5.orders, 0))
    results.append(Result("top5_customers ids, order, revenue, profit, orders = pandas", ok,
                          ", ".join(t5.customer_name.head(3)) + " ..."))

    # 12. concentration
    cc = q("04_business_analysis.sql", "customer_concentration").iloc[0]
    per_c = done.groupby("customer_id").rev.sum().sort_values(ascending=False)
    top5 = 100 * per_c.head(5).sum() / per_c.sum()
    top10p = 100 * per_c.head(int(0.10 * len(per_c))).sum() / per_c.sum()
    results.append(Result("customer_concentration top-5 and top-10% shares = pandas",
                          int(cc.customers) == len(per_c) and _close([cc.top5_share_pct, cc.top10pct_share_pct], [top5, top10p], 0.011),
                          f"top5={cc.top5_share_pct}% top10%={cc.top10pct_share_pct}%"))

    # 13. value tiers
    vt = q("04_business_analysis.sql", "customer_value_tiers")
    results.append(Result("customer_value_tiers cover every customer and all revenue",
                          int(vt.customers.sum()) == len(per_c) and _close([vt.revenue.sum()], [per_c.sum()]) and
                          list(vt.value_quartile) == [1, 2, 3, 4], f"{vt.customers.tolist()} customers per quartile"))
    fb = q("04_business_analysis.sql", "customer_frequency_bands")
    results.append(Result("customer_frequency_bands cover every customer", int(fb.customers.sum()) == len(per_c), ""))

    # 15. AOV by channel computed at order grain
    ao = q("04_business_analysis.sql", "aov_by_channel")
    ord_rev = done.groupby(["order_id", "sales_channel"]).rev.sum().reset_index()
    ex_ao = ord_rev.groupby("sales_channel").rev.agg(["count", "mean"]).reset_index().rename(columns={"count": "orders", "mean": "aov"})
    results.append(compare("aov_by_channel = pandas (one row per order)", ao[["sales_channel", "orders", "aov"]],
                           ex_ao, ["sales_channel"], ["orders", "aov"]))

    # 16. top category per month
    tc = q("04_business_analysis.sql", "top_category_per_month")
    ex_tc = done.groupby(["month_key", "category"]).rev.sum().reset_index().sort_values(["month_key", "rev"], ascending=[True, False]) \
        .drop_duplicates("month_key")
    results.append(Result("top_category_per_month = pandas", list(tc.top_category) == list(ex_tc.category) and len(tc) == 24, ""))

    # 17. placed vs completed
    pc = q("04_business_analysis.sql", "placed_vs_completed").iloc[0]
    o = pd.read_csv(processed / "orders.csv")
    results.append(Result("placed_vs_completed = pandas",
                          int(pc.placed_orders) == len(o) and int(pc.completed_orders) == (o.order_status == "Completed").sum() and
                          int(pc.cancelled_orders) == (o.order_status == "Cancelled").sum() and
                          int(pc.returned_orders) == (o.order_status == "Returned").sum(), ""))

    # 18. double-counting guard really shows the fan-out
    dg = q("04_business_analysis.sql", "double_count_guard").iloc[0]
    results.append(Result("double_count_guard: lines > distinct orders and distinct orders = pandas",
                          dg.completed_lines > dg.completed_orders and int(dg.completed_orders) == done.order_id.nunique(),
                          f"{int(dg.completed_lines):,} lines vs {int(dg.completed_orders):,} orders"))
    return results


def main() -> int:
    results = run()
    for r in results:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.name}" + (f"   ({r.detail})" if (not r.ok or r.detail) else ""))
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} SQL-vs-pandas checks passed (engine: SQLite {sqlite3.sqlite_version})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
