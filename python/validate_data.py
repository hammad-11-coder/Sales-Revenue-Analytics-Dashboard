#!/usr/bin/env python3
"""Validate the processed dataset: keys, domains, dates, reconciliation, and the cleaning log.

Exit code 0 = every check passed, 1 = at least one failed.

Usage:
    python python/validate_data.py
    python python/validate_data.py --report docs/validation_report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import kpi_definitions as kpi

REPO_ROOT = Path(__file__).resolve().parents[1]

# defect_manifest.json key -> cleaning_log rule_id that must find exactly that many rows
MANIFEST_TO_RULE = {
    "orders_duplicate_rows": "O1", "orders_alt_format_order_date": "O2a", "orders_alt_format_ship_date": "O2b",
    "orders_status_variants": "O3", "orders_ship_before_order": "O4", "orders_missing_customer_id": "O5a",
    "orders_missing_sales_channel": "O7", "items_duplicate_rows": "I1", "items_nonpositive_quantity": "I2",
    "items_bad_unit_price": "I3", "items_discount_as_percent": "I5", "items_negative_discount": "I6",
    "items_unknown_product": "I8", "items_orphan_order_reference": "I7",
    "items_in_orders_missing_customer": "I9", "items_missing_unit_cost": "I4",
    "customers_duplicate_rows": "C1", "customers_missing_segment": "C3", "customers_segment_variants": "C2",
    "customers_name_whitespace": "C4", "products_category_variants": "P1", "products_name_trailing_space": "P2",
}


@dataclass
class Check:
    group: str
    name: str
    passed: bool
    detail: str = ""


def _load(processed: Path) -> dict[str, pd.DataFrame]:
    names = ["regions", "products", "customers", "orders", "order_items", "dim_date", "fact_sales"]
    return {n: pd.read_csv(processed / f"{n}.csv") for n in names}


def run_checks(processed: Path, raw: Path | None = None) -> list[Check]:
    out: list[Check] = []

    def add(group, name, ok, detail=""):
        out.append(Check(group, name, bool(ok), str(detail)))

    t = _load(processed)
    reg, prod, cust, orders, items, dd, fact = (t[k] for k in
                                               ("regions", "products", "customers", "orders", "order_items",
                                                "dim_date", "fact_sales"))

    # ---- 1. completeness / primary keys
    for name, df in t.items():
        add("Structure", f"{name} is not empty", len(df) > 0, f"{len(df):,} rows")
    for name, col in [("regions", "region_id"), ("products", "product_id"), ("customers", "customer_id"),
                      ("orders", "order_id"), ("order_items", "order_item_id"), ("dim_date", "full_date"),
                      ("dim_date", "date_key"), ("fact_sales", "order_item_id")]:
        s = t[name][col]
        add("Primary keys", f"{name}.{col} unique and non-null", s.is_unique and s.notna().all(),
            f"{s.duplicated().sum()} duplicates, {s.isna().sum()} nulls")

    # ---- 2. foreign keys
    fks = [("orders.customer_id -> customers", orders.customer_id, cust.customer_id),
           ("orders.region_id -> regions", orders.region_id, reg.region_id),
           ("customers.home_region_id -> regions", cust.home_region_id, reg.region_id),
           ("order_items.order_id -> orders", items.order_id, orders.order_id),
           ("order_items.product_id -> products", items.product_id, prod.product_id),
           ("fact_sales.order_date -> dim_date", fact.order_date, dd.full_date),
           ("fact_sales.customer_id -> customers", fact.customer_id, cust.customer_id),
           ("fact_sales.product_id -> products", fact.product_id, prod.product_id),
           ("fact_sales.region_id -> regions", fact.region_id, reg.region_id)]
    for name, child, parent in fks:
        orphans = (~child.isin(parent)).sum()
        add("Foreign keys", name, orphans == 0, f"{orphans} orphan rows")
    add("Foreign keys", "every order has at least one line",
        orders.order_id.isin(items.order_id).all(), f"{(~orders.order_id.isin(items.order_id)).sum()} empty orders")

    # ---- 3. domain rules
    add("Domains", "order_status in {Completed, Cancelled, Returned}",
        orders.order_status.isin(kpi.ORDER_STATUSES).all(), orders.order_status.value_counts().to_dict())
    add("Domains", "quantity > 0 (integer)", (items.quantity > 0).all() and (items.quantity % 1 == 0).all(),
        f"min={items.quantity.min()}")
    add("Domains", "unit_price > 0", (items.unit_price > 0).all(), f"min={items.unit_price.min()}")
    add("Domains", "unit_cost > 0 and no nulls", (items.unit_cost > 0).all() and items.unit_cost.notna().all(),
        f"min={items.unit_cost.min()}")
    add("Domains", "0 <= discount <= 1", items.discount.between(0, 1).all(),
        f"range {items.discount.min()}..{items.discount.max()}")
    add("Domains", "segment in canonical set",
        cust.segment.isin(["Consumer", "Corporate", "Small Business", "Unknown"]).all(),
        cust.segment.value_counts().to_dict())
    add("Domains", "category in canonical set",
        prod.category.isin(["Technology", "Furniture", "Office Supplies", "Home & Kitchen", "Apparel"]).all(), "")
    add("Domains", "no leading/trailing whitespace in text keys and names",
        all((df[c] == df[c].str.strip()).all() for df, c in
            [(prod, "product_name"), (cust, "customer_name"), (orders, "sales_channel")]), "")

    # ---- 4. dates
    od = pd.to_datetime(orders.order_date, errors="coerce")
    sd = pd.to_datetime(orders.ship_date, errors="coerce")
    add("Dates", "order_date parses as ISO for every order", od.notna().all(), f"{od.isna().sum()} bad")
    add("Dates", "ship_date >= order_date when present", ((sd.isna()) | (sd >= od)).all(),
        f"{((sd < od)).sum()} violations")
    add("Dates", "ship_date within 30 days of order_date", ((sd.isna()) | ((sd - od).dt.days <= 30)).all(), "")
    add("Dates", "cancelled orders have no ship_date",
        orders.loc[orders.order_status == "Cancelled", "ship_date"].isna().all(), "")
    add("Dates", "order dates inside dim_date range",
        od.min() >= pd.Timestamp(dd.full_date.min()) and od.max() <= pd.Timestamp(dd.full_date.max()),
        f"{od.min().date()}..{od.max().date()}")
    full = pd.to_datetime(dd.full_date)
    expected_days = (full.max() - full.min()).days + 1
    add("Dates", "dim_date has one row per calendar day (no gaps)", len(dd) == expected_days and full.is_monotonic_increasing,
        f"{len(dd)} rows vs {expected_days} days")
    months = sorted(dd.month_key.unique())
    contiguous = all(kpi.shift_month_key(a, 1) == b for a, b in zip(months, months[1:]))
    add("Dates", "no missing months in dim_date", contiguous, f"{months[0]}..{months[-1]} ({len(months)} months)")
    add("Dates", "orders cover at least 24 months", od.dt.to_period("M").nunique() >= 24,
        f"{od.dt.to_period('M').nunique()} months with orders")
    mo = dd.drop_duplicates("month_key").sort_values("month_key")
    add("Dates", "month_label sorts chronologically via month_key",
        list(mo.month_key) == sorted(mo.month_key) and mo.month_label.is_unique, "")

    # ---- 5. reconciliation (independent recomputation from raw transactional columns)
    j = items.merge(orders[["order_id", "order_status"]], on="order_id", how="inner")
    rev = (j.quantity * j.unit_price * (1 - j.discount)).round(2)
    cost = (j.quantity * j.unit_cost).round(2)
    done = j.order_status == "Completed"
    exp_rev, exp_cost = rev[done].sum(), cost[done].sum()
    k = kpi.compute_kpis(fact)
    add("Reconciliation", "line count: order_items == fact_sales", len(items) == len(fact),
        f"{len(items):,} vs {len(fact):,}")
    add("Reconciliation", "revenue: fact_sales vs recomputed from order_items", abs(k["revenue"] - exp_rev) < 0.01,
        f"{k['revenue']:,.2f} vs {exp_rev:,.2f}")
    add("Reconciliation", "cost: fact_sales vs recomputed from order_items", abs(k["cost"] - exp_cost) < 0.01,
        f"{k['cost']:,.2f} vs {exp_cost:,.2f}")
    add("Reconciliation", "profit == revenue - cost", abs(k["profit"] - (exp_rev - exp_cost)) < 0.01,
        f"{k['profit']:,.2f}")
    add("Reconciliation", "line_profit == line_revenue - line_cost on every line",
        ((fact.line_revenue - fact.line_cost - fact.line_profit).abs() < 0.006).all(), "")
    add("Reconciliation", "gross_sales - discount_amount == line_revenue on every line",
        ((fact.gross_sales - fact.discount_amount - fact.line_revenue).abs() < 0.006).all(), "")
    by_status = fact.groupby("order_status").line_revenue.sum().sum()
    add("Reconciliation", "revenue across all statuses partitions cleanly", abs(by_status - fact.line_revenue.sum()) < 0.01, "")
    n_done = orders.loc[orders.order_status == "Completed", "order_id"].nunique()
    add("Reconciliation", "completed order count: orders table == fact_sales", n_done == k["orders"],
        f"{n_done:,} vs {k['orders']:,}")
    fm = fact.merge(dd[["full_date", "month_key"]], left_on="order_date", right_on="full_date")
    monthly = fm[fm.order_status == "Completed"].groupby("month_key").line_revenue.sum().sum()
    add("Reconciliation", "sum of monthly revenue == total revenue", abs(monthly - k["revenue"]) < 0.01, "")
    add("Reconciliation", "order count is not inflated by the order-line join (orders != lines)",
        k["orders"] < int((fact.order_status == "Completed").sum()), f"{k['orders']:,} orders vs "
        f"{int((fact.order_status == 'Completed').sum()):,} completed lines")

    # ---- 6. cleaning log vs injected-defect manifest
    log_path = processed / "cleaning_log.csv"
    add("Cleaning", "cleaning_log.csv exists and is non-empty", log_path.exists() and len(pd.read_csv(log_path)) > 0, "")
    manifest_path = (raw or REPO_ROOT / "data" / "raw") / "defect_manifest.json"
    if log_path.exists() and manifest_path.exists():
        log = pd.read_csv(log_path).set_index("rule_id").rows_affected
        m = json.loads(manifest_path.read_text())
        for key, rule in MANIFEST_TO_RULE.items():
            add("Cleaning", f"rule {rule} found exactly the {m[key]} injected '{key}' defects",
                int(log[rule]) == m[key], f"log={int(log[rule])} injected={m[key]}")
        tr = m["truth_rows"]
        exp_orders = tr["orders"] - int(log["O5a"]) - int(log["O8"])
        exp_items = tr["order_items"] - sum(int(log[r]) for r in ("I2", "I3", "I6", "I8", "I9"))
        add("Cleaning", "clean orders == truth - rejected orders", len(orders) == exp_orders,
            f"{len(orders):,} vs {exp_orders:,}")
        add("Cleaning", "clean order_items == truth - rejected lines", len(items) == exp_items,
            f"{len(items):,} vs {exp_items:,}")
        add("Cleaning", "clean customers/products == truth (dupes removed, nothing lost)",
            len(cust) == tr["customers"] and len(prod) == tr["products"], "")
    else:
        add("Cleaning", "defect_manifest.json available for cross-check", False, str(manifest_path))
    return out


def to_markdown(checks: list[Check]) -> str:
    lines = ["# Validation report", "",
             "Generated by `python/validate_data.py` (deterministic: no timestamps). "
             "All data in this repository is synthetic.", "",
             f"**{sum(c.passed for c in checks)} / {len(checks)} checks passed.**", ""]
    group = None
    for c in checks:
        if c.group != group:
            group = c.group
            lines += ["", f"## {group}", "", "| Result | Check | Detail |", "|---|---|---|"]
        lines.append(f"| {'PASS' if c.passed else '**FAIL**'} | {c.name} | {str(c.detail).replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--processed", type=Path, default=REPO_ROOT / "data" / "processed")
    ap.add_argument("--raw", type=Path, default=REPO_ROOT / "data" / "raw")
    ap.add_argument("--report", type=Path, help="write a markdown report here")
    a = ap.parse_args()
    checks = run_checks(a.processed, a.raw)
    group = None
    for c in checks:
        if c.group != group:
            group = c.group
            print(f"\n[{group}]")
        print(f"  {'PASS' if c.passed else 'FAIL'}  {c.name}" + (f"   ({c.detail})" if not c.passed else ""))
    failed = [c for c in checks if not c.passed]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(to_markdown(checks))
        print(f"report written to {a.report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
