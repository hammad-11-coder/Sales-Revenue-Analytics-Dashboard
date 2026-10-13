#!/usr/bin/env python3
"""Render a static PREVIEW of the dashboard layout with matplotlib.

IMPORTANT: this is NOT a Power BI export or screenshot. It is a design reference drawn from the real
processed data using the same 1280 x 720 grid as powerbi/PowerBI_Build_Guide.md, so the README has a
picture and the Power BI build has a target. The interactive deliverables are the Power BI build files
(powerbi/) and the Streamlit app (streamlit_app/).

Usage:
    python python/render_dashboard_preview.py                 # Year = 2025 view
    python python/render_dashboard_preview.py --year 0        # all 24 months (no comparison)
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

import kpi_definitions as kpi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NAVY, BLUE, GREEN, ORANGE, PURPLE, PINK, RED, GREY, LINE, PAGE = (
    "#0B2545", "#1D4ED8", "#15803D", "#C2410C", "#7C3AED", "#DB2777", "#B91C1C", "#6B7280", "#E5E7EB", "#F3F4F6")
CAT_COLORS = {"Technology": BLUE, "Furniture": ORANGE, "Office Supplies": PURPLE, "Home & Kitchen": GREEN, "Apparel": PINK}
W, H = 1280, 720
PX = 0.9  # 1 canvas px ~ 0.9 pt at a 16 in wide figure


def fs(px: float) -> float:
    return px * PX


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025, help="year slicer value, 0 = all years")
    ap.add_argument("--out", type=Path, default=ROOT / "dashboard_screenshots" / "dashboard_preview.png")
    a = ap.parse_args()

    t = kpi.load_processed()
    wide = kpi.enrich(t["fact_sales"], t)
    cal = sorted(int(k) for k in t["dim_date"]["month_key"].unique())
    years = [a.year] if a.year else sorted({k // 100 for k in cal})
    keys = [y * 100 + m for y in years for m in range(1, 13) if y * 100 + m in set(cal)]
    res = kpi.kpis_with_comparison(wide, keys, cal)
    k, prev, ch, plan = res["current"], res["previous"], res["change"], res["plan"]
    cur = wide[wide.month_key.isin(keys)]
    done = cur[cur.order_status == kpi.REVENUE_STATUS]
    labels = {int(r.month_key): r.month_short for r in wide.drop_duplicates("month_key").itertuples()}

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": LINE, "text.color": "#374151"})
    fig = plt.figure(figsize=(16, 9), dpi=120, facecolor=PAGE)
    bg = fig.add_axes([0, 0, 1, 1])
    bg.set_xlim(0, W); bg.set_ylim(H, 0); bg.axis("off")

    def panel(x, y, w, h, title=None, r=8):
        bg.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc="white", ec=LINE, lw=1))
        if title:
            bg.text(x + 12, y + 16, title, fontsize=fs(12), fontweight="bold", color=NAVY, va="center")

    def chart_ax(x, y, w, h, title, pad_l=10, pad_b=14, pad_t=30, pad_r=10):
        panel(x, y, w, h, title)
        ax = fig.add_axes([(x + pad_l) / W, 1 - (y + h - pad_b) / H, (w - pad_l - pad_r) / W, (h - pad_t - pad_b) / H])
        ax.set_facecolor("white")
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(LINE)
        ax.tick_params(colors=GREY, labelsize=fs(10), length=0)
        return ax

    cr = lambda s: s / 1e7  # noqa: E731

    # ---------------------------------------------------------------- header
    bg.text(16, 22, "Sales & Revenue Analytics Dashboard", fontsize=fs(22), fontweight="bold", color=NAVY, va="center")
    bg.text(16, 50, "Turning Retail Transaction Data into Business Insights", fontsize=fs(12), color=GREY, va="center")
    panel(860, 8, 404, 52)
    bg.text(872, 24, f"Reporting period: {labels[cal[0]]} {cal[0] // 100} – {labels[cal[-1]]} {cal[-1] // 100}",
            fontsize=fs(11), fontweight="bold", color=NAVY, va="center")
    bg.text(872, 44, "Source: SYNTHETIC retail transactions (generated, seed 42)", fontsize=fs(10), color=GREY, va="center")
    bg.text(W - 16, 66, "LAYOUT PREVIEW (matplotlib) - not a Power BI export", fontsize=fs(8), color=RED, ha="right", va="center")

    # ---------------------------------------------------------------- slicers
    sl = [("Year", str(a.year) if a.year else "All"), ("Month", "All"), ("Region", "All"),
          ("Product Category", "All"), ("Product", "All"), ("Customer Segment", "All")]
    for i, (n, v) in enumerate(sl):
        x = 16 + i * 198
        panel(x, 72, 190, 36, r=6)
        bg.text(x + 10, 84, n, fontsize=fs(8), color=GREY, va="center")
        bg.text(x + 10, 98, v, fontsize=fs(11), color=NAVY, va="center", fontweight="bold")
        bg.text(x + 176, 91, "v", fontsize=fs(10), color=GREY, va="center", ha="center")
    panel(1204, 72, 60, 36, r=6)
    bg.text(1234, 90, "Clear", fontsize=fs(11), color=BLUE, va="center", ha="center", fontweight="bold")

    # ---------------------------------------------------------------- KPI cards
    def ctext(g, pp=False):
        if g is None:
            return "–", GREY
        return f"{'▲' if g >= 0 else '▼'} {abs(g) * (1 if pp else 100):.1f}{' pp' if pp else '%'}", GREEN if g >= 0 else RED

    pv = lambda key, f: f(prev[key]) if prev else "–"  # noqa: E731
    cards = [("Total Revenue", kpi.format_inr(k["revenue"]), ctext(ch["revenue"]), pv("revenue", kpi.format_inr)),
             ("Total Profit", kpi.format_inr(k["profit"]), ctext(ch["profit"]), pv("profit", kpi.format_inr)),
             ("Total Orders", f"{k['orders']:,}", ctext(ch["orders"]), pv("orders", lambda v: f"{v:,}")),
             ("Total Customers", f"{k['customers']:,}", ctext(ch["customers"]), pv("customers", lambda v: f"{v:,}")),
             ("Profit Margin", kpi.format_pct(k["margin"]), ctext(ch["margin_pp"], True), pv("margin", kpi.format_pct)),
             ("Average Order Value", kpi.format_inr(k["aov"]), ctext(ch["aov"]), pv("aov", kpi.format_inr))]
    for i, (n, v, (ct, cc), p) in enumerate(cards):
        x = 16 + i * 209
        panel(x, 116, 203, 74, r=10)
        bg.text(x + 14, 130, n, fontsize=fs(10), color=GREY, va="center")
        bg.text(x + 14, 154, v, fontsize=fs(22), fontweight="bold", color=NAVY, va="center")
        bg.text(x + 14, 176, ct, fontsize=fs(11), color=cc, va="center", fontweight="bold")
        bg.text(x + 189, 176, f"prev {p}", fontsize=fs(8), color=GREY, va="center", ha="right")
    bg.text(W - 16, 196, f"KPI comparison: {plan['label']}", fontsize=fs(8), color=GREY, ha="right", va="center")

    # ---------------------------------------------------------------- D: trend
    mo = done.groupby("month_key").agg(rev=("line_revenue", "sum"), prof=("line_profit", "sum")).reindex(keys, fill_value=0)
    ax = chart_ax(16, 202, 520, 172, "Revenue & profit trend (₹ crore)", pad_l=34, pad_r=70)
    x = range(len(mo))
    ax.plot(x, cr(mo.rev), color=BLUE, lw=2.2, marker="o", ms=4)
    ax.plot(x, cr(mo.prof), color=GREEN, lw=2.2, marker="o", ms=4)
    ax.set_xticks(list(x)); ax.set_xticklabels([labels[m] for m in mo.index])
    ax.yaxis.grid(True, color=LINE, lw=0.6); ax.set_axisbelow(True); ax.set_ylim(0, None)
    ax.text(len(mo) - 0.6, cr(mo.rev.iloc[-1]), "Revenue", color=BLUE, fontsize=fs(10), va="center", fontweight="bold")
    ax.text(len(mo) - 0.6, cr(mo.prof.iloc[-1]), "Profit", color=GREEN, fontsize=fs(10), va="center", fontweight="bold")
    ax.set_xlim(-0.3, len(mo) + 0.2)

    # ---------------------------------------------------------------- E: region
    r = done.groupby("region").line_revenue.sum().sort_values()
    ax = chart_ax(544, 202, 330, 172, "Sales by region (₹ crore)", pad_l=60, pad_r=40)
    cols = [GREEN if v == r.max() else ORANGE if v == r.min() else BLUE for v in r]
    ax.barh(r.index, cr(r), color=cols, height=0.62)
    for i, v in enumerate(cr(r)):
        ax.text(v + 0.03, i, f"{v:.2f}", va="center", fontsize=fs(10), color="#374151")
    ax.set_xlim(0, cr(r).max() * 1.2); ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)

    # ---------------------------------------------------------------- F: category donut
    cat = done.groupby("category").line_revenue.sum().sort_values(ascending=False)
    panel(882, 202, 382, 172, "Sales by category")
    axd = fig.add_axes([(882 + 6) / W, 1 - (374 - 6) / H, 172 / W, 138 / H])
    axd.pie(cat.values, colors=[CAT_COLORS[c] for c in cat.index], startangle=90, counterclock=False,
            wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
    axd.text(0, 0.08, kpi.format_inr(k["revenue"]), ha="center", va="center", fontsize=fs(11), fontweight="bold", color=NAVY)
    axd.text(0, -0.2, "revenue", ha="center", va="center", fontsize=fs(8), color=GREY)
    for i, (c, v) in enumerate(cat.items()):
        y = 244 + i * 24
        bg.add_patch(FancyBboxPatch((1076, y - 5), 10, 10, boxstyle="round,pad=0,rounding_size=2", fc=CAT_COLORS[c], ec="none"))
        bg.text(1092, y, c, fontsize=fs(10), color="#374151", va="center")
        bg.text(1252, y, f"{v / cat.sum() * 100:.1f}%", fontsize=fs(10), color="#374151", va="center", ha="right", fontweight="bold")

    # ---------------------------------------------------------------- G: top 10 products
    p = done.groupby("product_name").line_revenue.sum().nlargest(10).sort_values()
    ax = chart_ax(16, 382, 420, 180, "Top 10 products by revenue (₹ crore)", pad_l=150, pad_r=34, pad_t=28)
    ax.barh(p.index, cr(p), color=BLUE, height=0.64)
    for i, v in enumerate(cr(p)):
        ax.text(v + 0.02, i, f"{v:.2f}", va="center", fontsize=fs(8), color="#374151")
    ax.tick_params(axis="y", labelsize=fs(8.5), colors="#374151"); ax.set_xticks([]); ax.set_xlim(0, cr(p).max() * 1.18)
    ax.spines["bottom"].set_visible(False)

    # ---------------------------------------------------------------- H: profit by category
    pc = done.groupby("category").agg(profit=("line_profit", "sum"), revenue=("line_revenue", "sum"))
    pc["m"] = pc.profit / pc.revenue
    overall = pc.profit.sum() / pc.revenue.sum()
    pc = pc.sort_values("profit")
    ax = chart_ax(444, 382, 330, 180, "Profit by category (₹ crore, margin)", pad_l=96, pad_r=70, pad_t=28)
    cols = [RED if r_.profit < 0 else ORANGE if r_.m < overall / 2 else BLUE for r_ in pc.itertuples()]
    ax.barh(pc.index, cr(pc.profit), color=cols, height=0.6)
    for i, r_ in enumerate(pc.itertuples()):
        ax.text(cr(r_.profit) + 0.01, i, f"{cr(r_.profit):.2f} ({r_.m * 100:.1f}%)", va="center", fontsize=fs(9), color="#374151")
    ax.tick_params(axis="y", labelsize=fs(9), colors="#374151"); ax.set_xticks([]); ax.set_xlim(0, cr(pc.profit).max() * 1.5)
    ax.spines["bottom"].set_visible(False)

    # ---------------------------------------------------------------- I: monthly clustered columns
    ax = chart_ax(782, 382, 482, 180, "Sales vs profit by month (₹ crore)", pad_l=34, pad_t=30)
    xs = list(range(len(mo)))
    ax.bar([i - 0.2 for i in xs], cr(mo.rev), width=0.38, color=BLUE, label="Revenue")
    ax.bar([i + 0.2 for i in xs], cr(mo.prof), width=0.38, color=GREEN, label="Profit")
    ax.set_xticks(xs); ax.set_xticklabels([labels[m] for m in mo.index])
    ax.yaxis.grid(True, color=LINE, lw=0.6); ax.set_axisbelow(True)
    ax.legend(loc="upper left", ncol=2, frameon=False, fontsize=fs(9), handlelength=1, borderaxespad=0.2)

    # ---------------------------------------------------------------- J: top 5 customers
    panel(16, 570, 620, 142, "Top 5 customers")
    tc = (done.groupby(["customer_id", "customer_name"]).agg(o=("order_id", "nunique"), rv=("line_revenue", "sum"),
          pf=("line_profit", "sum")).reset_index().sort_values(["rv", "customer_id"], ascending=[False, True]).head(5))
    heads = [("Customer ID", 30, "left"), ("Customer Name", 130, "left"), ("Total Orders", 380, "right"),
             ("Total Revenue", 500, "right"), ("Total Profit", 610, "right")]
    for hname, hx, ha in heads:
        bg.text(hx, 608, hname, fontsize=fs(9.5), fontweight="bold", color=NAVY, ha=ha, va="center")
    bg.plot([26, 626], [617, 617], color=LINE, lw=1)
    for i, r_ in enumerate(tc.itertuples()):
        y = 631 + i * 16
        for val, (_, hx, ha) in zip([r_.customer_id, r_.customer_name, f"{r_.o}", kpi.format_inr(r_.rv, False),
                                     kpi.format_inr(r_.pf, False)], heads):
            bg.text(hx, y, val, fontsize=fs(10), color="#374151", ha=ha, va="center")

    # ---------------------------------------------------------------- K: insights
    panel(644, 570, 620, 142, "Key business insights")
    for i, line in enumerate(kpi.build_insights(cur, k, plan, ch)):
        y = 610 + i * 20
        bg.add_patch(FancyBboxPatch((656, y - 8), 3, 18, boxstyle="square,pad=0", fc=BLUE, ec="none"))
        wrapped = textwrap.shorten(line, width=118, placeholder="…")
        bg.text(666, y + 1, wrapped, fontsize=fs(9), color="#374151", va="center")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=120, facecolor=PAGE)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
