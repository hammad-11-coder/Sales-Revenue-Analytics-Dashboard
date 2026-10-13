"""Single source of truth for KPI and business-rule logic in Python.

The same definitions are written out in prose in ``docs/business_rules.md``, as SQL in
``sql/03_transformations.sql`` / ``sql/04_business_analysis.sql`` and as DAX in
``powerbi/DAX_Measures.md``. If a definition changes, change it in all four places and
re-run ``python/verify_sql_against_python.py`` and the test-suite.

Business rules (summary)
------------------------
* Currency: Indian rupees (INR). No tax, shipping or returns-handling cost is modelled.
* Line revenue  = ROUND(quantity * unit_price * (1 - discount), 2)
* Line cost     = ROUND(quantity * unit_cost, 2)
* Line profit   = line revenue - line cost
* An order is *placed* when it exists in ``orders`` (any status).
* An order is *completed* when ``order_status == 'Completed'``. Only completed orders
  count towards revenue, cost, profit, orders, customers, margin and AOV.
  Cancelled orders never shipped; Returned orders were refunded -> both excluded.
* Profit margin = profit / revenue.  AOV = revenue / completed orders.
  Both are undefined (None) when the denominator is zero.
* Previous comparable period: if exactly ONE calendar month is selected, compare with
  the previous month; otherwise compare the same set of months one year earlier.
  If any month of the comparison period lies outside the calendar, there is no
  comparison (None) rather than a misleading partial figure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

REVENUE_STATUS = "Completed"
ORDER_STATUSES = ("Completed", "Cancelled", "Returned")
REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


# ----------------------------------------------------------------------------- line level
def line_metrics(items: pd.DataFrame) -> pd.DataFrame:
    """Add gross_sales, discount_amount, line_revenue, line_cost, line_profit."""
    out = items.copy()
    out["gross_sales"] = (out["quantity"] * out["unit_price"]).round(2)
    out["line_revenue"] = (out["quantity"] * out["unit_price"] * (1 - out["discount"])).round(2)
    out["discount_amount"] = (out["gross_sales"] - out["line_revenue"]).round(2)
    out["line_cost"] = (out["quantity"] * out["unit_cost"]).round(2)
    out["line_profit"] = (out["line_revenue"] - out["line_cost"]).round(2)
    return out


FACT_COLUMNS = [
    "order_item_id", "order_id", "order_date", "ship_date", "customer_id", "product_id", "region_id",
    "sales_channel", "order_status", "quantity", "unit_price", "unit_cost", "discount",
    "gross_sales", "discount_amount", "line_revenue", "line_cost", "line_profit", "is_completed",
]


def build_fact_sales(orders: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """One row per order line, joined once to its order header (many-to-one, validated)."""
    header = orders[["order_id", "order_date", "ship_date", "customer_id", "region_id",
                     "sales_channel", "order_status"]]
    fact = items.merge(header, on="order_id", how="inner", validate="many_to_one")
    fact = line_metrics(fact)
    fact["is_completed"] = (fact["order_status"] == REVENUE_STATUS).astype(int)
    return fact[FACT_COLUMNS]


# ----------------------------------------------------------------------------- KPIs
def safe_div(numerator, denominator):
    """Division that returns None for a zero / missing denominator (mirrors DAX DIVIDE -> BLANK)."""
    if numerator is None or denominator is None or pd.isna(numerator) or pd.isna(denominator):
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def compute_kpis(df: pd.DataFrame) -> dict:
    """KPIs for any slice of the (enriched) fact table. Safe on empty input."""
    if len(df) == 0:
        return {"revenue": 0.0, "cost": 0.0, "profit": 0.0, "orders": 0, "customers": 0,
                "margin": None, "aov": None, "placed_orders": 0, "cancelled_orders": 0,
                "returned_orders": 0, "cancellation_rate": None, "return_rate": None}
    done = df[df["order_status"] == REVENUE_STATUS]
    revenue = round(float(done["line_revenue"].sum()), 2)
    cost = round(float(done["line_cost"].sum()), 2)
    profit = round(revenue - cost, 2)
    orders = int(done["order_id"].nunique())
    placed = int(df["order_id"].nunique())
    cancelled = int(df.loc[df["order_status"] == "Cancelled", "order_id"].nunique())
    returned = int(df.loc[df["order_status"] == "Returned", "order_id"].nunique())
    return {
        "revenue": revenue, "cost": cost, "profit": profit, "orders": orders,
        "customers": int(done["customer_id"].nunique()),
        "margin": safe_div(profit, revenue), "aov": safe_div(revenue, orders),
        "placed_orders": placed, "cancelled_orders": cancelled, "returned_orders": returned,
        "cancellation_rate": safe_div(cancelled, placed), "return_rate": safe_div(returned, placed),
    }


def pct_change(current, previous):
    """(current - previous) / |previous|, or None when previous is missing or zero.

    Dividing by the ABSOLUTE previous value (same as the DAX Profit Growth %) means moving from a loss
    of 30 to a loss of 15 reads as an improvement (+50%), not a decline.
    """
    if previous is None or current is None or pd.isna(previous) or previous == 0:
        return None
    return (current - previous) / abs(previous)


# ----------------------------------------------------------------------------- period comparison
def shift_month_key(month_key: int, n: int) -> int:
    """Shift a yyyymm integer by n months (n may be negative)."""
    year, month = divmod(int(month_key), 100)
    idx = year * 12 + (month - 1) + n
    return (idx // 12) * 100 + (idx % 12) + 1


def comparison_plan(selected_keys: Iterable[int], calendar_keys: Iterable[int]) -> dict:
    """Decide how the current selection is compared. Mirrors the DAX [Comparison Mode] logic."""
    selected = sorted(set(int(k) for k in selected_keys))
    calendar = set(int(k) for k in calendar_keys)
    if not selected:
        return {"mode": "NONE", "prior_keys": None, "available": False, "label": "no period selected"}
    if len(selected) == 1:
        mode, shift, label = "MoM", -1, "vs previous month"
    else:
        mode, shift, label = "YoY", -12, "vs same period last year"
    prior = sorted(shift_month_key(k, shift) for k in selected)
    available = set(prior) <= calendar
    return {"mode": mode, "prior_keys": prior if available else None, "available": available,
            "label": label if available else f"{label} (not available: outside data range)"}


def kpis_with_comparison(df: pd.DataFrame, selected_keys: Iterable[int], calendar_keys: Iterable[int]) -> dict:
    """KPIs for the selected months and, when comparable, for the previous period.

    ``df`` must already carry the non-date filters (region, category, ...) but NOT the date filter.
    """
    selected_keys = sorted(set(int(k) for k in selected_keys))
    plan = comparison_plan(selected_keys, calendar_keys)
    current = compute_kpis(df[df["month_key"].isin(selected_keys)])
    previous = compute_kpis(df[df["month_key"].isin(plan["prior_keys"])]) if plan["available"] else None
    # An empty current selection (no completed orders) has nothing to compare: report blank, never "-100%".
    comparable = previous is not None and current["orders"] > 0
    change = {}
    for k in ("revenue", "profit", "orders", "customers", "aov"):
        change[k] = pct_change(current[k], previous[k]) if comparable else None
    change["margin_pp"] = ((current["margin"] - previous["margin"]) * 100
                           if comparable and current["margin"] is not None and previous["margin"] is not None
                           else None)
    return {"plan": plan, "current": current, "previous": previous, "change": change}


# ----------------------------------------------------------------------------- formatting
def _indian_group(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + out


def format_inr(value, compact: bool = True) -> str:
    """Rupee formatting. compact -> '₹12.34 Cr' / '₹5.60 L'; otherwise full Indian digit grouping."""
    if value is None or pd.isna(value):
        return "–"
    sign = "-" if value < 0 else ""
    v = abs(float(value))
    if compact:
        if v >= 1e7:
            return f"{sign}₹{v / 1e7:.2f} Cr"
        if v >= 1e5:
            return f"{sign}₹{v / 1e5:.2f} L"
    return f"{sign}₹{_indian_group(round(v))}"


def format_pct(value, digits: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{value * 100:+.{digits}f}%" if signed else f"{value * 100:.{digits}f}%"


# ----------------------------------------------------------------------------- insights
def build_insights(cur: pd.DataFrame, k: dict, plan: dict, change: dict) -> list[str]:
    """Five plain-language insights for a selection (mirrors the DAX 'Insight n' measures).

    ``cur`` is the selected slice of the enriched fact table, ``k`` its KPIs, ``plan``/``change``
    come from :func:`kpis_with_comparison`.
    """
    d = cur[cur["order_status"] == REVENUE_STATUS]
    if d.empty:
        return ["No sales for the current selection."]
    out = []
    g = change["revenue"]
    out.append(f"Revenue is {format_inr(k['revenue'])}, " +
               (f"{'up' if g >= 0 else 'down'} {abs(g) * 100:.1f}% {plan['label']}" if g is not None
                else "with no comparable period for this selection") + f". Profit margin is {format_pct(k['margin'])}.")
    reg = d.groupby("region")["line_revenue"].sum().sort_values(ascending=False)
    out.append(f"{reg.index[0]} is the top region with {format_inr(reg.iloc[0])} "
               f"({format_pct(reg.iloc[0] / reg.sum())} of revenue).")
    cat = d.groupby("category").agg(rev=("line_revenue", "sum"), prof=("line_profit", "sum"))
    cat["m"] = cat["prof"] / cat["rev"]
    best, low = cat["prof"].idxmax(), cat["m"].idxmin()
    out.append(f"{best} earns the most profit ({format_inr(cat['prof'][best])}). " +
               ("It is the only category in this selection." if len(cat) == 1 else
                (f"It also has the lowest margin at {format_pct(cat['m'][low])}" if best == low
                 else f"{low} has the lowest margin at {format_pct(cat['m'][low])}")
                + (" and is loss-making." if cat["prof"][low] < 0 else ".")))
    prod = d.groupby("product_name")["line_revenue"].sum().sort_values(ascending=False)
    out.append(f"{prod.index[0]} is the top product: {format_inr(prod.iloc[0])} "
               f"({format_pct(prod.iloc[0] / prod.sum())} of revenue).")
    cu = d.groupby("customer_id")["line_revenue"].sum().sort_values(ascending=False)
    out.append(f"The top 5 customers account for {format_pct(cu.head(5).sum() / cu.sum())} of revenue "
               f"across {len(cu):,} active customers.")
    return out


# ----------------------------------------------------------------------------- loading
def load_processed(processed_dir: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Load the processed CSVs into DataFrames with sensible dtypes."""
    d = Path(processed_dir) if processed_dir else PROCESSED_DIR
    out = {
        "regions": pd.read_csv(d / "regions.csv"),
        "products": pd.read_csv(d / "products.csv"),
        "customers": pd.read_csv(d / "customers.csv", parse_dates=["signup_date"]),
        "orders": pd.read_csv(d / "orders.csv", parse_dates=["order_date", "ship_date"]),
        "order_items": pd.read_csv(d / "order_items.csv"),
        "dim_date": pd.read_csv(d / "dim_date.csv", parse_dates=["full_date"]),
        "fact_sales": pd.read_csv(d / "fact_sales.csv", parse_dates=["order_date", "ship_date"]),
    }
    return out


def enrich(fact: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach dimension attributes to the fact table for analysis (Streamlit, notebook, tests)."""
    wide = (fact
            .merge(tables["products"][["product_id", "product_name", "category", "subcategory"]],
                   on="product_id", how="left", validate="many_to_one")
            .merge(tables["customers"][["customer_id", "customer_name", "segment"]],
                   on="customer_id", how="left", validate="many_to_one")
            .merge(tables["regions"][["region_id", "region", "state", "city"]],
                   on="region_id", how="left", validate="many_to_one")
            .merge(tables["dim_date"][["full_date", "cal_year", "month_num", "month_name", "month_short",
                                       "month_key", "month_label", "cal_quarter"]],
                   left_on="order_date", right_on="full_date", how="left", validate="many_to_one")
            .drop(columns="full_date"))
    return wide
