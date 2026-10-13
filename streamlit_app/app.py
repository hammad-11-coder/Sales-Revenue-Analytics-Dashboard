"""Sales & Revenue Analytics Dashboard: Streamlit edition (optional companion to the Power BI report).

Runs the same business rules as the SQL and DAX (see python/kpi_definitions.py): completed orders only,
previous-month comparison when one month is selected, same-period-last-year otherwise, blank when the
comparison period is outside the data. All data is SYNTHETIC.

    pip install -r streamlit_app/requirements.txt
    streamlit run streamlit_app/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import kpi_definitions as kpi  # noqa: E402

NAVY, BLUE, GREEN, ORANGE, PURPLE, RED, GREY = "#0B2545", "#1D4ED8", "#15803D", "#C2410C", "#7C3AED", "#B91C1C", "#6B7280"
# fixed colour per category (colour follows the entity); palette checked with the dataviz validator
CAT_COLORS = {"Technology": BLUE, "Furniture": ORANGE, "Office Supplies": PURPLE, "Home & Kitchen": GREEN, "Apparel": "#DB2777"}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]
FILTERS = {"f_year": "Year", "f_month": "Month", "f_region": "Region", "f_category": "Product Category",
           "f_product": "Product", "f_segment": "Customer Segment"}

st.set_page_config(page_title="Sales & Revenue Analytics", page_icon="📊", layout="wide")
st.markdown(
    f"""<style>
    .block-container {{padding-top: 1.2rem; max-width: 1500px;}}
    h1, h2, h3 {{color: {NAVY};}}
    .kpi {{border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 14px; background: #fff;}}
    .kpi .t {{font-size: 12px; color: {GREY};}} .kpi .v {{font-size: 26px; font-weight: 600; color: {NAVY};}}
    .kpi .c {{font-size: 13px; font-weight: 600;}} .kpi .p {{font-size: 11px; color: {GREY};}}
    .insight {{border-left: 4px solid {BLUE}; padding: 4px 10px; margin: 6px 0; font-size: 14px;}}
    </style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load() -> tuple[pd.DataFrame, list[int]]:
    t = kpi.load_processed()
    return kpi.enrich(t["fact_sales"], t), sorted(int(k) for k in t["dim_date"]["month_key"].unique())


def clear_filters() -> None:
    for key in FILTERS:
        st.session_state[key] = []


def change_text(g, suffix="%", scale=100.0):
    if g is None:
        return "–", GREY
    return f"{'▲' if g >= 0 else '▼'} {abs(g) * (scale if suffix == '%' else 1):.1f}{' pp' if suffix == ' pp' else '%'}", \
        GREEN if g >= 0 else RED


def card(col, title, value, change, prev):
    txt, color = change
    col.markdown(f"<div class='kpi'><div class='t'>{title}</div><div class='v'>{value}</div>"
                 f"<div class='c' style='color:{color}'>{txt}</div><div class='p'>Previous period: {prev}</div></div>",
                 unsafe_allow_html=True)


wide, calendar_keys = load()

# ----------------------------------------------------------------------------- header
st.title("Sales & Revenue Analytics Dashboard")
st.caption("Turning Retail Transaction Data into Business Insights  |  Reporting period: "
           f"{pd.to_datetime(str(calendar_keys[0]), format='%Y%m').strftime('%b %Y')} – "
           f"{pd.to_datetime(str(calendar_keys[-1]), format='%Y%m').strftime('%b %Y')}  |  "
           "Source: **synthetic** retail transactions (generated, seed 42). Not real company performance.")

# ----------------------------------------------------------------------------- filters (empty = all, like a Power BI slicer)
with st.sidebar:
    st.header("Filters")
    years = st.multiselect("Year", sorted({k // 100 for k in calendar_keys}), key="f_year")
    months = st.multiselect("Month", MONTH_NAMES, key="f_month")
    regions = st.multiselect("Region", sorted(wide.region.unique()), key="f_region")
    cats = st.multiselect("Product Category", sorted(wide.category.unique()), key="f_category")
    prods = st.multiselect("Product", sorted(wide[wide.category.isin(cats)].product_name.unique() if cats
                                             else wide.product_name.unique()), key="f_product")
    segs = st.multiselect("Customer Segment", sorted(wide.segment.unique()), key="f_segment")
    st.button("Clear filters", on_click=clear_filters, use_container_width=True)
    st.caption("No selection = all values.")

base = wide
for col, sel in (("region", regions), ("category", cats), ("product_name", prods), ("segment", segs)):
    if sel:
        base = base[base[col].isin(sel)]
sel_years = years or sorted({k // 100 for k in calendar_keys})
sel_months = [MONTH_NAMES.index(m) + 1 for m in months] or list(range(1, 13))
selected_keys = [y * 100 + m for y in sel_years for m in sel_months if y * 100 + m in set(calendar_keys)]
cur = base[base.month_key.isin(selected_keys)]
res = kpi.kpis_with_comparison(base, selected_keys, calendar_keys)
k, prev, ch, plan = res["current"], res["previous"], res["change"], res["plan"]
empty = cur[cur.order_status == kpi.REVENUE_STATUS].empty
dash = "–"

# ----------------------------------------------------------------------------- KPI cards
cols = st.columns(6)
fmt = lambda v, f: dash if (empty or v is None) else f(v)  # noqa: E731
card(cols[0], "Total Revenue", fmt(k["revenue"], kpi.format_inr), change_text(ch["revenue"]),
     fmt(prev and prev["revenue"], kpi.format_inr))
card(cols[1], "Total Profit", fmt(k["profit"], kpi.format_inr), change_text(ch["profit"]),
     fmt(prev and prev["profit"], kpi.format_inr))
card(cols[2], "Total Orders", dash if empty else f"{k['orders']:,}", change_text(ch["orders"]),
     dash if not prev or empty else f"{prev['orders']:,}")
card(cols[3], "Total Customers", dash if empty else f"{k['customers']:,}", change_text(ch["customers"]),
     dash if not prev or empty else f"{prev['customers']:,}")
card(cols[4], "Profit Margin", fmt(k["margin"], kpi.format_pct), change_text(ch["margin_pp"], " pp"),
     fmt(prev and prev["margin"], kpi.format_pct))
card(cols[5], "Average Order Value", fmt(k["aov"], kpi.format_inr), change_text(ch["aov"]),
     fmt(prev and prev["aov"], kpi.format_inr))
st.caption(f"Comparison: {plan['label']}")

if empty:
    st.info("No completed sales for the current selection. Clear or change a filter.")
    st.stop()

done = cur[cur.order_status == kpi.REVENUE_STATUS]
layout = dict(margin=dict(l=10, r=10, t=40, b=10), height=330, plot_bgcolor="white", paper_bgcolor="white",
              font=dict(family="Segoe UI, Arial", size=12, color="#374151"), legend=dict(orientation="h", y=-0.2))
cr = lambda s: s / 1e7  # noqa: E731

# monthly series over the selected months, with zero rows for months without sales (no missing months)
labels = {int(r.month_key): r.month_label for r in wide.drop_duplicates("month_key").itertuples()}
monthly = (done.groupby("month_key").agg(revenue=("line_revenue", "sum"), profit=("line_profit", "sum"))
           .reindex(sorted(selected_keys), fill_value=0.0).reset_index())
monthly["label"] = monthly.month_key.map(labels)

c1, c2, c3 = st.columns([5, 3.3, 3.8])
with c1:
    f = go.Figure()
    f.add_scatter(x=monthly.label, y=cr(monthly.revenue), name="Revenue", mode="lines+markers", line=dict(color=BLUE, width=3))
    f.add_scatter(x=monthly.label, y=cr(monthly.profit), name="Profit", mode="lines+markers", line=dict(color=GREEN, width=3))
    f.update_layout(title="Revenue & profit trend", yaxis_title="₹ crore", **layout)
    f.update_xaxes(type="category", tickangle=-45)
    st.plotly_chart(f, use_container_width=True)
with c2:
    r = done.groupby("region").line_revenue.sum().sort_values()
    colors = [GREEN if v == r.max() else ORANGE if v == r.min() and len(r) > 1 else BLUE for v in r]
    f = go.Figure(go.Bar(x=cr(r), y=r.index, orientation="h", marker_color=colors, text=[f"{v:.2f}" for v in cr(r)],
                         textposition="outside"))
    f.update_layout(title="Sales by region (₹ crore)", **{**layout, "legend": dict()})
    st.plotly_chart(f, use_container_width=True)
with c3:
    cat = done.groupby("category").line_revenue.sum().sort_values(ascending=False)
    f = go.Figure(go.Pie(labels=cat.index, values=cat.values, hole=0.6, sort=False, textinfo="label+percent",
                         marker=dict(colors=[CAT_COLORS[c] for c in cat.index], line=dict(color="white", width=2))))
    f.add_annotation(text=f"<b>{kpi.format_inr(k['revenue'])}</b><br>revenue", showarrow=False, font=dict(size=15, color=NAVY))
    f.update_layout(title="Sales by category", showlegend=False, **{**layout, "legend": dict()})
    st.plotly_chart(f, use_container_width=True)

d1, d2, d3 = st.columns([4.2, 3.3, 4.8])
with d1:
    p = done.groupby("product_name").line_revenue.sum().nlargest(10).sort_values()
    f = go.Figure(go.Bar(x=cr(p), y=p.index, orientation="h", marker_color=BLUE, text=[f"{v:.2f}" for v in cr(p)],
                         textposition="outside"))
    f.update_layout(title="Top 10 products by revenue (₹ crore)", **{**layout, "legend": dict()})
    st.plotly_chart(f, use_container_width=True)
with d2:
    pc = done.groupby("category").agg(profit=("line_profit", "sum"), revenue=("line_revenue", "sum"))
    overall = pc.profit.sum() / pc.revenue.sum()
    pc["margin"] = pc.profit / pc.revenue
    pc = pc.sort_values("profit")
    colors = [RED if r.profit < 0 else ORANGE if r.margin < overall / 2 else BLUE for r in pc.itertuples()]
    f = go.Figure(go.Bar(x=cr(pc.profit), y=pc.index, orientation="h", marker_color=colors,
                         text=[f"{v:.2f}  ({m * 100:.1f}%)" for v, m in zip(cr(pc.profit), pc.margin)], textposition="outside"))
    f.update_layout(title="Profit by category (₹ crore, margin)", **{**layout, "legend": dict()})
    st.plotly_chart(f, use_container_width=True)
with d3:
    f = go.Figure()
    f.add_bar(x=monthly.label, y=cr(monthly.revenue), name="Revenue", marker_color=BLUE)
    f.add_bar(x=monthly.label, y=cr(monthly.profit), name="Profit", marker_color=GREEN)
    f.update_layout(title="Sales vs profit by month (₹ crore)", barmode="group", **layout)
    f.update_xaxes(type="category", tickangle=-45)
    st.plotly_chart(f, use_container_width=True)

e1, e2 = st.columns([6.2, 6.2])
with e1:
    st.subheader("Top 5 customers")
    tc = (done.groupby(["customer_id", "customer_name"]).agg(total_orders=("order_id", "nunique"),
          total_revenue=("line_revenue", "sum"), total_profit=("line_profit", "sum")).reset_index()
          .sort_values(["total_revenue", "customer_id"], ascending=[False, True]).head(5))
    tc.insert(0, "rank", range(1, len(tc) + 1))
    tc["total_revenue"] = tc.total_revenue.map(lambda v: kpi.format_inr(v, compact=False))
    tc["total_profit"] = tc.total_profit.map(lambda v: kpi.format_inr(v, compact=False))
    st.dataframe(tc, hide_index=True, use_container_width=True)
with e2:
    st.subheader("Key business insights")
    for line in kpi.build_insights(cur, k, plan, ch):
        st.markdown(f"<div class='insight'>{line}</div>", unsafe_allow_html=True)
