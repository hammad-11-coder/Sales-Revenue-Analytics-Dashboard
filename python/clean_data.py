#!/usr/bin/env python3
"""Clean the raw CSVs in ``data/raw`` and write analysis-ready files to ``data/processed``.

Every decision is a numbered rule (see ``docs/business_rules.md`` -> "Cleaning rules"):

* rows that can be repaired deterministically are repaired and counted;
* rows that cannot be trusted are *rejected*, written to ``rejected_rows.csv`` with the
  rule that rejected them, and never silently dropped;
* every rule (including those that found nothing) is recorded in ``cleaning_log.csv``.

Usage:
    python python/clean_data.py
    python python/clean_data.py --raw data/raw --out data/processed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import kpi_definitions as kpi

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIN_DATE = "2024-01-01"
DEFAULT_MAX_DATE = "2025-12-31"

STATUS_MAP = {"completed": "Completed", "cancelled": "Cancelled", "canceled": "Cancelled", "returned": "Returned"}
SEGMENT_MAP = {"consumer": "Consumer", "corporate": "Corporate", "small business": "Small Business"}
CATEGORY_MAP = {"technology": "Technology", "furniture": "Furniture", "office supplies": "Office Supplies",
                "home & kitchen": "Home & Kitchen", "apparel": "Apparel"}


class CleaningLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.rejected: list[pd.DataFrame] = []

    def add(self, rule_id: str, table: str, description: str, action: str, n: int) -> None:
        self.rows.append({"rule_id": rule_id, "table": table, "description": description,
                          "action": action, "rows_affected": int(n)})

    def reject(self, df: pd.DataFrame, mask, table: str, rule_id: str, description: str, key: str) -> pd.DataFrame:
        """Log + quarantine the masked rows and return the frame without them."""
        mask = pd.Series(np.asarray(mask), index=df.index)
        bad = df[mask]
        self.add(rule_id, table, description, "rejected", len(bad))
        if len(bad):
            rec = pd.DataFrame({
                "table": table, "rule_id": rule_id, "reason": description,
                "record_key": bad[key].astype(str).to_numpy(),
                "raw_record": [json.dumps({k: (None if pd.isna(v) else v) for k, v in r.items()}, default=str)
                               for r in bad.to_dict("records")],
            })
            self.rejected.append(rec)
        return df[~mask].copy()

    def log_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def rejected_frame(self) -> pd.DataFrame:
        cols = ["table", "rule_id", "reason", "record_key", "raw_record"]
        return pd.concat(self.rejected, ignore_index=True) if self.rejected else pd.DataFrame(columns=cols)


def parse_dates(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse ISO, dd/mm/yyyy (day-first, Indian convention) and dd-Mon-yyyy strings.

    Returns (parsed datetimes, mask of values that were NOT in ISO format but parsed OK).
    """
    s = s.astype("string").str.strip()
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    dby = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    parsed = iso.fillna(dmy).fillna(dby)
    return parsed, (iso.isna() & parsed.notna())


# ----------------------------------------------------------------------------- dimensions
def clean_regions(raw: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = raw.copy()
    for c in ("region", "state", "city"):
        df[c] = df[c].astype("string").str.strip()
    df = log.reject(df, df.duplicated("region_id", keep="first"), "regions", "R1",
                    "Duplicate region_id (keep first)", "region_id")
    df["region_id"] = df["region_id"].astype(int)
    return df


def clean_products(raw: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = raw.copy()
    dup = df.duplicated(keep="first")
    log.add("P0", "products", "Exact duplicate product rows", "dropped", dup.sum())
    df = df[~dup].copy()
    df = log.reject(df, df.duplicated("product_id", keep="first"), "products", "P0b",
                    "Duplicate product_id with conflicting attributes (keep first)", "product_id")

    name_clean = df["product_name"].astype("string").str.split().str.join(" ")
    log.add("P2", "products", "Trim / collapse whitespace in product_name", "repaired",
            (name_clean != df["product_name"]).sum())
    df["product_name"] = name_clean

    cat_norm = df["category"].astype("string").str.strip().str.lower().map(CATEGORY_MAP)
    log.add("P1", "products", "Standardise category spelling / case / whitespace to the 5 canonical categories",
            "repaired", ((cat_norm != df["category"]) & cat_norm.notna()).sum())
    df["category"] = cat_norm.fillna(df["category"])
    df = log.reject(df, cat_norm.isna().to_numpy(), "products", "P1b", "Category not in the canonical list", "product_id")
    df["subcategory"] = df["subcategory"].astype("string").str.strip()

    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df["unit_cost"] = pd.to_numeric(df["unit_cost"], errors="coerce")
    bad = df["unit_price"].isna() | df["unit_cost"].isna() | (df["unit_price"] <= 0) | (df["unit_cost"] <= 0) \
        | (df["unit_cost"] >= df["unit_price"])
    df = log.reject(df, bad, "products", "P3", "List price/standard cost missing, non-positive, or cost >= price",
                    "product_id")
    return df[["product_id", "product_name", "category", "subcategory", "unit_price", "unit_cost"]].reset_index(drop=True)


def clean_customers(raw: pd.DataFrame, regions: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    df = raw.copy()
    dup = df.duplicated(keep="first")
    log.add("C1", "customers", "Exact duplicate customer rows", "dropped", dup.sum())
    df = df[~dup].copy()
    df = log.reject(df, df.duplicated("customer_id", keep="first"), "customers", "C1b",
                    "Duplicate customer_id with conflicting attributes (keep first)", "customer_id")

    name_clean = df["customer_name"].astype("string").str.split().str.join(" ")
    log.add("C4", "customers", "Trim / collapse whitespace in customer_name", "repaired",
            (name_clean != df["customer_name"]).sum())
    df["customer_name"] = name_clean

    raw_seg = df["segment"].astype("string")
    norm = raw_seg.str.strip().str.lower().map(SEGMENT_MAP)
    log.add("C2", "customers", "Standardise segment spelling / case / whitespace", "repaired",
            ((norm != raw_seg) & norm.notna()).sum())
    missing = raw_seg.isna() | (raw_seg.str.strip() == "")
    unrecognised = norm.isna() & ~missing
    log.add("C3", "customers", "Missing segment set to 'Unknown' (kept: customer still has valid sales)",
            "repaired", missing.sum())
    log.add("C3b", "customers", "Unrecognised segment text set to 'Unknown'", "repaired", unrecognised.sum())
    df["segment"] = norm.fillna("Unknown")

    df["home_region_id"] = pd.to_numeric(df["home_region_id"], errors="coerce")
    df = log.reject(df, ~df["home_region_id"].isin(regions["region_id"]), "customers", "C5",
                    "home_region_id missing or not in regions", "customer_id")
    df["home_region_id"] = df["home_region_id"].astype(int)
    parsed, _ = parse_dates(df["signup_date"])
    df["signup_date"] = parsed.dt.strftime("%Y-%m-%d")
    return df[["customer_id", "customer_name", "segment", "home_region_id", "signup_date"]].reset_index(drop=True)


# ----------------------------------------------------------------------------- orders
def clean_orders_header(raw: pd.DataFrame, customers: pd.DataFrame, regions: pd.DataFrame, log: CleaningLog,
                        min_date: str, max_date: str) -> pd.DataFrame:
    df = raw.copy()
    dup = df.duplicated(keep="first")
    log.add("O1", "orders", "Exact duplicate order rows", "dropped", dup.sum())
    df = df[~dup].copy()
    df = log.reject(df, df.duplicated("order_id", keep="first"), "orders", "O1b",
                    "Duplicate order_id with conflicting attributes (keep first)", "order_id")

    od, od_non_iso = parse_dates(df["order_date"])
    sd, sd_non_iso = parse_dates(df["ship_date"])
    log.add("O2a", "orders", "order_date in dd/mm/yyyy or dd-Mon-yyyy format parsed to ISO", "repaired", od_non_iso.sum())
    log.add("O2b", "orders", "ship_date in dd/mm/yyyy or dd-Mon-yyyy format parsed to ISO", "repaired", sd_non_iso.sum())
    df["order_date"], df["ship_date"] = od, sd
    df = log.reject(df, df["order_date"].isna(), "orders", "O2c", "order_date missing or unparseable", "order_id")
    out_of_range = (df["order_date"] < pd.Timestamp(min_date)) | (df["order_date"] > pd.Timestamp(max_date))
    df = log.reject(df, out_of_range, "orders", "O2d",
                    f"order_date outside the reporting window {min_date}..{max_date}", "order_id")

    norm = df["order_status"].astype("string").str.strip().str.lower().map(STATUS_MAP)
    log.add("O3", "orders", "Standardise order_status spelling / case / whitespace (incl. 'Canceled')", "repaired",
            ((norm != df["order_status"]) & norm.notna()).sum())
    df["order_status"] = norm.fillna(df["order_status"])
    df = log.reject(df, norm.isna().to_numpy(), "orders", "O3b", "order_status not one of Completed/Cancelled/Returned",
                    "order_id")

    before = df["ship_date"].notna() & (df["ship_date"] < df["order_date"])
    log.add("O4", "orders", "ship_date earlier than order_date: ship_date set to NULL", "repaired", before.sum())
    df.loc[before, "ship_date"] = pd.NaT
    canc_shipped = (df["order_status"] == "Cancelled") & df["ship_date"].notna()
    log.add("O4b", "orders", "Cancelled order with a ship_date: ship_date set to NULL", "repaired", canc_shipped.sum())
    df.loc[canc_shipped, "ship_date"] = pd.NaT

    cust = df["customer_id"].astype("string").str.strip()
    df["customer_id"] = cust
    df = log.reject(df, cust.isna() | (cust == ""), "orders", "O5a", "customer_id missing", "order_id")
    df = log.reject(df, ~df["customer_id"].isin(customers["customer_id"]), "orders", "O5b",
                    "customer_id not found in customers", "order_id")

    df["region_id"] = pd.to_numeric(df["region_id"], errors="coerce")
    df = log.reject(df, ~df["region_id"].isin(regions["region_id"]), "orders", "O6", "region_id missing or not in regions",
                    "order_id")
    df["region_id"] = df["region_id"].astype(int)

    ch = df["sales_channel"].astype("string").str.strip()
    log.add("O7", "orders", "Missing sales_channel set to 'Unknown'", "repaired", (ch.isna() | (ch == "")).sum())
    df["sales_channel"] = ch.where(ch.notna() & (ch != ""), "Unknown")
    return df[["order_id", "order_date", "ship_date", "customer_id", "region_id", "sales_channel", "order_status"]]


def clean_items(raw: pd.DataFrame, valid_order_ids: set, raw_order_ids: set, products: pd.DataFrame,
                log: CleaningLog) -> pd.DataFrame:
    df = raw.copy()
    dup = df.duplicated(keep="first")
    log.add("I1", "order_items", "Exact duplicate order-line rows", "dropped", dup.sum())
    df = df[~dup].copy()
    df = log.reject(df, df.duplicated("order_item_id", keep="first"), "order_items", "I1b",
                    "Duplicate order_item_id with conflicting attributes (keep first)", "order_item_id")

    for c in ("quantity", "unit_price", "unit_cost", "discount"):
        # float64 even when every value is a whole number, so repairs such as 15 -> 0.15 cannot fail on an int column
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")

    df = log.reject(df, df["quantity"].isna() | (df["quantity"] <= 0), "order_items", "I2",
                    "quantity missing, zero or negative", "order_item_id")
    df = log.reject(df, df["unit_price"].isna() | (df["unit_price"] <= 0), "order_items", "I3",
                    "unit_price missing, zero or negative", "order_item_id")

    # discounts entered as whole percentages (e.g. 15 instead of 0.15) are converted, others validated
    pct = (df["discount"] > 1) & (df["discount"] <= 100)
    log.add("I5", "order_items", "discount in (1, 100] interpreted as a percentage and divided by 100", "repaired", pct.sum())
    df.loc[pct, "discount"] = df.loc[pct, "discount"] / 100
    nodisc = df["discount"].isna()
    log.add("I5b", "order_items", "Missing discount treated as 0", "repaired", nodisc.sum())
    df.loc[nodisc, "discount"] = 0.0
    df = log.reject(df, (df["discount"] < 0) | (df["discount"] > 1), "order_items", "I6",
                    "discount negative or above 100% after conversion", "order_item_id")

    df = log.reject(df, ~df["product_id"].isin(products["product_id"]), "order_items", "I8",
                    "product_id not found in products", "order_item_id")
    df = log.reject(df, ~df["order_id"].isin(raw_order_ids), "order_items", "I7",
                    "order_id does not exist in orders (orphan line)", "order_item_id")
    df = log.reject(df, ~df["order_id"].isin(valid_order_ids), "order_items", "I9",
                    "order_id belongs to an order rejected during header cleaning", "order_item_id")

    cost_missing = df["unit_cost"].isna()
    std_cost = df["product_id"].map(products.set_index("product_id")["unit_cost"])
    log.add("I4", "order_items", "Missing unit_cost imputed from the product master standard cost", "repaired",
            cost_missing.sum())
    df.loc[cost_missing, "unit_cost"] = std_cost[cost_missing]
    df = log.reject(df, df["unit_cost"] <= 0, "order_items", "I4b", "unit_cost zero or negative", "order_item_id")

    df["quantity"] = df["quantity"].astype(int)
    df["unit_price"] = df["unit_price"].round(2)
    df["unit_cost"] = df["unit_cost"].round(2)
    df["discount"] = df["discount"].round(4)
    return df[["order_item_id", "order_id", "product_id", "quantity", "unit_price", "unit_cost", "discount"]]


# ----------------------------------------------------------------------------- date dimension
def build_dim_date(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    d = pd.date_range(start, end, freq="D")
    q = d.quarter
    out = pd.DataFrame({"full_date": d.strftime("%Y-%m-%d")})
    out["date_key"] = d.strftime("%Y%m%d").astype(int)
    out["cal_year"] = d.year
    out["quarter_num"] = q
    out["cal_quarter"] = ["Q" + str(x) for x in q]
    out["year_quarter"] = [f"{y}-Q{x}" for y, x in zip(d.year, q)]
    out["month_num"] = d.month
    out["month_name"] = d.strftime("%B")
    out["month_short"] = d.strftime("%b")
    out["month_key"] = d.year * 100 + d.month
    out["month_label"] = d.strftime("%b %Y")
    out["day_of_month"] = d.day
    out["week_of_year"] = d.isocalendar().week.astype(int).to_numpy()
    out["day_of_week_num"] = d.dayofweek + 1
    out["day_name"] = d.strftime("%A")
    out["is_weekend"] = (d.dayofweek >= 5).astype(int)
    return out


# ----------------------------------------------------------------------------- pipeline
def run(raw_dir: Path, out_dir: Path, min_date: str = DEFAULT_MIN_DATE, max_date: str = DEFAULT_MAX_DATE) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = CleaningLog()
    raw = {n: pd.read_csv(raw_dir / f"{n}.csv", dtype=str) for n in
           ("regions", "products", "customers", "orders", "order_items")}
    raw_rows = {k: len(v) for k, v in raw.items()}

    regions = clean_regions(raw["regions"], log)
    products = clean_products(raw["products"], log)
    customers = clean_customers(raw["customers"], regions, log)
    orders = clean_orders_header(raw["orders"], customers, regions, log, min_date, max_date)
    items = clean_items(raw["order_items"], set(orders["order_id"]), set(raw["orders"]["order_id"].dropna()),
                        products, log)

    # O8: orders with no surviving lines cannot contribute and would distort order counts
    no_lines = ~orders["order_id"].isin(items["order_id"])
    orders = log.reject(orders, no_lines, "orders", "O8", "Order has no valid order lines after cleaning", "order_id")

    fact = kpi.build_fact_sales(orders, items)
    # internal reconciliation: header/line join must not gain or lose any line
    assert len(fact) == len(items), "fact_sales lost or duplicated lines"
    assert abs(fact["line_revenue"].sum() - kpi.line_metrics(items)["line_revenue"].sum()) < 0.01

    years = orders["order_date"].dt.year
    dim_date = build_dim_date(pd.Timestamp(int(years.min()), 1, 1), pd.Timestamp(int(years.max()), 12, 31))

    # write ISO strings, blanks for NULL
    orders_out = orders.copy()
    orders_out["order_date"] = orders_out["order_date"].dt.strftime("%Y-%m-%d")
    orders_out["ship_date"] = orders_out["ship_date"].dt.strftime("%Y-%m-%d")
    fact_out = fact.copy()
    fact_out["order_date"] = fact_out["order_date"].dt.strftime("%Y-%m-%d")
    fact_out["ship_date"] = fact_out["ship_date"].dt.strftime("%Y-%m-%d")

    outputs = {"regions": regions, "products": products, "customers": customers, "orders": orders_out,
               "order_items": items, "dim_date": dim_date, "fact_sales": fact_out}
    for name, df in outputs.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    log.log_frame().to_csv(out_dir / "cleaning_log.csv", index=False)
    log.rejected_frame().to_csv(out_dir / "rejected_rows.csv", index=False)
    summary = {"rows_raw": raw_rows,
               "rows_clean": {k: int(len(v)) for k, v in outputs.items()},
               "rows_rejected_total": int(len(log.rejected_frame())),
               "reporting_window": [min_date, max_date]}
    (out_dir / "cleaning_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=REPO_ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "processed")
    ap.add_argument("--min-date", default=DEFAULT_MIN_DATE)
    ap.add_argument("--max-date", default=DEFAULT_MAX_DATE)
    a = ap.parse_args()
    s = run(a.raw, a.out, a.min_date, a.max_date)
    print(f"Cleaned data written to {a.out}")
    for k in s["rows_clean"]:
        raw_n = s["rows_raw"].get(k)
        print(f"  {k:12s} raw={raw_n if raw_n is not None else '-':>7}  clean={s['rows_clean'][k]:>7,}")
    print(f"  rows quarantined in rejected_rows.csv: {s['rows_rejected_total']:,}")


if __name__ == "__main__":
    main()
