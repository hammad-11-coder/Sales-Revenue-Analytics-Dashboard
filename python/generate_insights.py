#!/usr/bin/env python3
"""Compute the business insights and the Power BI reference values from the processed data.

Outputs (deterministic, no timestamps):
  docs/key_insights.md              five insights with the numbers behind them
  docs/powerbi_reference_values.md  expected KPI values for named slicer selections, so the
                                    Power BI report can be checked against known-good numbers
and, with --update-readme, replaces the block between the INSIGHTS markers in README.md.

Usage:
    python python/generate_insights.py [--update-readme]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

import kpi_definitions as kpi

REPO_ROOT = Path(__file__).resolve().parents[1]
MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
          7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def load() -> tuple[pd.DataFrame, list[int]]:
    t = kpi.load_processed()
    wide = kpi.enrich(t["fact_sales"], t)
    return wide, sorted(t["dim_date"]["month_key"].unique())


def completed(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["order_status"] == kpi.REVENUE_STATUS]


def pct(x, d=1):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def insights(w: pd.DataFrame) -> list[str]:
    c = completed(w)
    total = c["line_revenue"].sum()
    k24, k25 = (kpi.compute_kpis(w[w.cal_year == y]) for y in (2024, 2025))
    rev_g, prof_g = kpi.pct_change(k25["revenue"], k24["revenue"]), kpi.pct_change(k25["profit"], k24["profit"])
    pp = (k25["margin"] - k24["margin"]) * 100

    reg = c.groupby("region").agg(rev=("line_revenue", "sum"), prof=("line_profit", "sum"))
    reg["margin"] = reg.prof / reg.rev
    best, worst = reg.rev.idxmax(), reg.rev.idxmin()

    cat = c.groupby("category").agg(rev=("line_revenue", "sum"), prof=("line_profit", "sum"))
    cat["margin"] = cat.prof / cat.rev
    top_profit_cat = cat.prof.idxmax()
    low_margin_cat = cat.margin.idxmin()
    cat_year = c.groupby(["category", "cal_year"]).apply(
        lambda d: d.line_profit.sum() / d.line_revenue.sum(), include_groups=False).unstack()

    prod = c.groupby("product_name").agg(rev=("line_revenue", "sum"), prof=("line_profit", "sum")).sort_values("rev", ascending=False)
    top3_share = prod.rev.head(3).sum() / total

    cu = c.groupby("customer_id").line_revenue.sum().sort_values(ascending=False)
    top5, top10p = cu.head(5).sum() / cu.sum(), cu.head(int(0.10 * len(cu))).sum() / cu.sum()

    festive = c[c.month_num.isin([10, 11])].groupby("cal_year").line_revenue.sum() / c.groupby("cal_year").line_revenue.sum()

    return [
        f"**Revenue grew {pct(rev_g)} in 2025 but profit grew {pct(prof_g)}, so margin slipped {abs(pp):.1f} pp.** "
        f"Revenue rose from {kpi.format_inr(k24['revenue'])} to {kpi.format_inr(k25['revenue'])}; margin moved from "
        f"{pct(k24['margin'])} to {pct(k25['margin'])} (completed orders only).",
        f"**{best} is the strongest region** with {kpi.format_inr(reg.rev[best])} ({pct(reg.rev[best] / total)} of revenue). "
        f"{worst} is the smallest at {kpi.format_inr(reg.rev[worst])} ({pct(reg.rev[worst] / total)}); "
        f"regional margins are tightly grouped ({pct(reg.margin.min())} to {pct(reg.margin.max())}), so the gap is volume, not pricing.",
        f"**{top_profit_cat} earns the most profit ({kpi.format_inr(cat.prof[top_profit_cat])}) but {low_margin_cat} is the weak spot.** "
        f"{low_margin_cat} contributes {pct(cat.rev[low_margin_cat] / total)} of revenue at a {pct(cat.margin[low_margin_cat])} margin, "
        f"falling from {pct(cat_year.loc[low_margin_cat, 2024])} in 2024 to {pct(cat_year.loc[low_margin_cat, 2025])} in 2025 "
        f"because Furniture costs rise faster than its prices while discounts stay deep in this synthetic dataset. Apparel has the highest margin ({pct(cat.margin['Apparel'])}).",
        f"**'{prod.index[0]}' is the top product** at {kpi.format_inr(prod.rev.iloc[0])} ({pct(prod.rev.iloc[0] / total)} of revenue); "
        f"the top three products together make up {pct(top3_share)}, showing a revenue base dominated by high-ticket Technology items.",
        f"**Customer concentration is moderate.** The top 5 customers contribute {pct(top5)} of revenue, while the top 10% of customers "
        f"({int(0.10 * len(cu))} of {len(cu):,}) contribute {pct(top10p)}. Festive months (Oct-Nov) delivered {pct(festive[2024])} "
        f"of 2024 revenue and {pct(festive[2025])} of 2025 revenue.",
    ]


# --------------------------------------------------------------------------- reference scenarios
SCENARIOS = [
    ("A", "No slicers (all 24 months)", {}),
    ("B", "Year = 2025", {"years": [2025]}),
    ("C", "Year = 2024", {"years": [2024]}),
    ("D", "Year = 2025, Month = October", {"years": [2025], "months": [10]}),
    ("E", "Year = 2024, Month = January", {"years": [2024], "months": [1]}),
    ("F", "Year = 2025, Month = January (previous month is Dec 2024)", {"years": [2025], "months": [1]}),
    ("G", "Year = 2025, Months = Jan-Jun", {"years": [2025], "months": [1, 2, 3, 4, 5, 6]}),
    ("H", "Year = 2025, Region = West", {"years": [2025], "region": ["West"]}),
    ("I", "Year = 2025, Category = Furniture, Segment = Corporate",
     {"years": [2025], "category": ["Furniture"], "segment": ["Corporate"]}),
    ("J", "Years = 2024 + 2025, Month = March (two Marches: prior period outside data)", {"months": [3]}),
    ("K", "Year = 2025, Months = Jan + Mar (non-contiguous: compared with Jan + Mar 2024 only)",
     {"years": [2025], "months": [1, 3]}),
    ("L", "Year = 2025, Month = January, Region = Central, Category = Apparel, Segment = Small Business "
          "(EMPTY now, but December 2024 had sales: growth must be blank, not -100%)",
     {"years": [2025], "months": [1], "region": ["Central"], "category": ["Apparel"], "segment": ["Small Business"]}),
]


def select(w: pd.DataFrame, cal: list[int], spec: dict) -> dict:
    years = spec.get("years", sorted({k // 100 for k in cal}))
    months = spec.get("months", list(range(1, 13)))
    keys = [y * 100 + m for y in years for m in months if y * 100 + m in set(cal)]
    d = w
    for col in ("region", "category", "segment", "product_name"):
        if col in spec:
            d = d[d[col].isin(spec[col])]
    return kpi.kpis_with_comparison(d, keys, cal)


def reference_table(w: pd.DataFrame, cal: list[int]) -> str:
    rows = ["| ID | Slicer selection | Revenue (₹) | Profit (₹) | Orders | Customers | Margin | AOV (₹) | Comparison | Prior revenue (₹) | Revenue growth | Profit growth | Margin change |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|"]
    for sid, label, spec in SCENARIOS:
        r = select(w, cal, spec)
        c, p, ch, plan = r["current"], r["previous"], r["change"], r["plan"]
        comp = plan["label"] if plan["available"] else "n/a (blank)"
        rows.append(
            f"| {sid} | {label} | {c['revenue']:,.2f} | {c['profit']:,.2f} | {c['orders']:,} | {c['customers']:,} | "
            f"{pct(c['margin'], 2)} | {'–' if c['aov'] is None else format(c['aov'], ',.2f')} | {comp} | {(p['revenue'] if p else None) and format(p['revenue'], ',.2f') or '–'} | "
            f"{pct(ch['revenue'], 2)} | {pct(ch['profit'], 2)} | "
            f"{'–' if ch['margin_pp'] is None else format(ch['margin_pp'], '+.2f') + ' pp'} |")
    return "\n".join(rows)


def find_empty_selection(w: pd.DataFrame, cal: list[int]) -> str:
    """Find a real slicer combination with zero completed revenue (to test blank handling)."""
    c = completed(w)
    have = set(zip(c.region, c.category, c.segment, c.month_key))
    for reg in sorted(w.region.unique()):
        for cat in sorted(w.category.unique()):
            for seg in sorted(w.segment.unique()):
                for mk in cal:
                    if (reg, cat, seg, mk) not in have:
                        return (f"Region = {reg}, Category = {cat}, Segment = {seg}, "
                                f"Year = {mk // 100}, Month = {MONTHS[mk % 100]}")
    return ""


def breakdown_tables(w: pd.DataFrame) -> str:
    c = completed(w)
    out = []
    reg = c.groupby("region").agg(revenue=("line_revenue", "sum"), profit=("line_profit", "sum"), orders=("order_id", "nunique"))
    reg["margin"] = reg.profit / reg.revenue
    out += ["### Revenue and profit by region (all 24 months, no other slicers)", "",
            "| Region | Revenue (₹) | Profit (₹) | Orders | Margin |", "|---|---:|---:|---:|---:|"]
    for n, r in reg.sort_values("revenue", ascending=False).iterrows():
        out.append(f"| {n} | {r.revenue:,.2f} | {r.profit:,.2f} | {int(r.orders):,} | {pct(r.margin, 2)} |")
    cat = c.groupby("category").agg(revenue=("line_revenue", "sum"), profit=("line_profit", "sum"))
    cat["margin"] = cat.profit / cat.revenue
    cat["share"] = cat.revenue / cat.revenue.sum()
    out += ["", "### Revenue share and profit by category (all 24 months)", "",
            "| Category | Revenue (₹) | Share | Profit (₹) | Margin |", "|---|---:|---:|---:|---:|"]
    for n, r in cat.sort_values("revenue", ascending=False).iterrows():
        out.append(f"| {n} | {r.revenue:,.2f} | {pct(r.share, 2)} | {r.profit:,.2f} | {pct(r.margin, 2)} |")
    prod = c.groupby("product_name").agg(revenue=("line_revenue", "sum")).sort_values("revenue", ascending=False).head(10)
    out += ["", "### Top 10 products by revenue (all 24 months)", "", "| Rank | Product | Revenue (₹) |", "|---:|---|---:|"]
    for i, (n, r) in enumerate(prod.iterrows(), 1):
        out.append(f"| {i} | {n} | {r.revenue:,.2f} |")
    cu = c.groupby(["customer_id", "customer_name"]).agg(orders=("order_id", "nunique"), revenue=("line_revenue", "sum"),
                                                          profit=("line_profit", "sum")) \
        .reset_index().sort_values("revenue", ascending=False).head(5)
    out += ["", "### Top 5 customers by revenue (all 24 months)", "",
            "| Rank | Customer ID | Customer | Orders | Revenue (₹) | Profit (₹) |", "|---:|---|---|---:|---:|---:|"]
    for i, r in enumerate(cu.itertuples(), 1):
        out.append(f"| {i} | {r.customer_id} | {r.customer_name} | {r.orders} | {r.revenue:,.2f} | {r.profit:,.2f} |")
    m = c.groupby("month_key").agg(revenue=("line_revenue", "sum"), profit=("line_profit", "sum"))
    out += ["", "### Monthly revenue and profit (all slicers cleared)", "", "| Month | Revenue (₹) | Profit (₹) |", "|---|---:|---:|"]
    for mk, r in m.iterrows():
        out.append(f"| {MONTHS[mk % 100]} {mk // 100} | {r.revenue:,.2f} | {r.profit:,.2f} |")
    return "\n".join(out)


def write_outputs(update_readme: bool) -> None:
    w, cal = load()
    ins = insights(w)
    ins_md = "\n".join(f"{i}. {t}" for i, t in enumerate(ins, 1))
    (REPO_ROOT / "docs" / "key_insights.md").write_text(
        "# Key business insights\n\n"
        "Computed by `python/generate_insights.py` from the processed **synthetic** dataset (seed 42), completed orders only. "
        "These are findings about generated data, not about any real business.\n\n" + ins_md + "\n")

    ref = ("# Power BI reference values\n\n"
           "Use these numbers to check the Power BI report once it is built (see `powerbi/PowerBI_Build_Guide.md`, step 12). "
           "They come from `python/generate_insights.py`, which reads the same processed CSVs and applies the same business rules "
           "as the DAX measures. All data is **synthetic**.\n\n"
           "Set the slicers exactly as described, read the six KPI cards, and compare. Amounts are in rupees to the paisa; "
           "the cards will show compact `₹ Cr / ₹ L` forms of the same numbers. A difference of more than ₹0.01 means a measure, "
           "relationship or filter is wrong.\n\n"
           "## KPI scenarios\n\n" + reference_table(w, cal) + "\n\n"
           "How to read the comparison columns: with exactly one month selected the card compares with the previous month; with any "
           "other period it compares with the same months one year earlier; if any prior month falls outside the Jan 2024 - Dec 2025 "
           "calendar the comparison is blank (`n/a`), never a partial figure.\n\n"
           + (f"**Empty-selection test:** `{find_empty_selection(w, cal)}` has no completed sales. "
              "Cards must show blank (not an error, not 0%), charts must show no bars, and rankings must stay empty.\n\n"
              if find_empty_selection(w, cal) else "")
           + breakdown_tables(w) + "\n")
    (REPO_ROOT / "docs" / "powerbi_reference_values.md").write_text(ref)

    if update_readme:
        p = REPO_ROOT / "README.md"
        text = p.read_text()
        new = re.sub(r"(<!-- INSIGHTS:START -->).*?(<!-- INSIGHTS:END -->)",
                     lambda m: f"{m.group(1)}\n{ins_md}\n{m.group(2)}", text, flags=re.S)
        if new == text and "<!-- INSIGHTS:START -->" not in text:
            raise SystemExit("README.md has no INSIGHTS markers")
        p.write_text(new)
    print(ins_md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update-readme", action="store_true")
    write_outputs(ap.parse_args().update_readme)


if __name__ == "__main__":
    main()
