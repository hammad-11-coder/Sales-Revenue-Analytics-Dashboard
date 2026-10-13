"""Regression tests for defects found in the independent QA review."""
import sqlite3

import pandas as pd

import kpi_definitions as kpi
import verify_sql_against_python as vsp


def _slice(wide, **f):
    d = wide
    for col, val in f.items():
        d = d[d[col] == val]
    return d


def test_empty_selection_with_populated_prior_month_gives_blank_growth_not_minus_100(wide, calendar_keys):
    base = _slice(wide, region="Central", category="Apparel", segment="Small Business")
    r = kpi.kpis_with_comparison(base, [202501], calendar_keys)
    assert r["current"]["orders"] == 0 and r["current"]["revenue"] == 0
    assert r["previous"] is not None and r["previous"]["revenue"] > 0     # December 2024 had sales
    assert all(v is None for v in r["change"].values())                   # no -100 %


def test_normal_selection_still_gets_growth(wide, calendar_keys):
    r = kpi.kpis_with_comparison(wide, [202510], calendar_keys)
    assert r["change"]["revenue"] is not None and r["change"]["margin_pp"] is not None


def test_insight3_wording_with_several_categories_never_claims_only_one(wide, calendar_keys):
    for keys in ([202401, 202402], list(range(202501, 202513)), [202510]):
        cur = wide[wide.month_key.isin(keys)]
        res = kpi.kpis_with_comparison(wide, keys, calendar_keys)
        text = " ".join(kpi.build_insights(cur, res["current"], res["plan"], res["change"]))
        assert cur[cur.order_status == "Completed"].category.nunique() > 1
        assert "only category" not in text


def test_insight3_single_category_and_empty(wide, calendar_keys):
    one = _slice(wide, category="Apparel")
    keys = [202510]
    cur = one[one.month_key.isin(keys)]
    res = kpi.kpis_with_comparison(one, keys, calendar_keys)
    assert any("only category" in t for t in kpi.build_insights(cur, res["current"], res["plan"], res["change"]))
    assert kpi.build_insights(wide.iloc[0:0], kpi.compute_kpis(wide.iloc[0:0]), {"label": ""}, {"revenue": None}) == \
        ["No sales for the current selection."]


def test_sql_fact_view_has_every_csv_column(root):
    con = vsp.load_sqlite(root / "data" / "processed")
    for stmt in vsp.split_statements((root / "sql" / "03_transformations.sql").read_text()):
        con.execute(stmt)
    view_cols = {r[1] for r in con.execute("PRAGMA table_info(vw_fact_sales)")}
    csv_cols = set(pd.read_csv(root / "data" / "processed" / "fact_sales.csv", nrows=1).columns)
    assert csv_cols <= view_cols, csv_cols - view_cols
    view = pd.read_sql_query("SELECT order_item_id, line_revenue, discount_amount FROM vw_fact_sales ORDER BY order_item_id", con)
    csv = pd.read_csv(root / "data" / "processed" / "fact_sales.csv", usecols=["order_item_id", "line_revenue", "discount_amount"]) \
        .sort_values("order_item_id").reset_index(drop=True)
    assert (view.order_item_id.values == csv.order_item_id.values).all()
    assert (view.line_revenue - csv.line_revenue).abs().max() < 0.006
    assert (view.discount_amount - csv.discount_amount).abs().max() < 0.011


def test_sql_profit_growth_uses_abs_base(root):
    text = (root / "sql" / "04_business_analysis.sql").read_text()
    assert "NULLIF(ABS(prev.profit), 0)" in text and "NULLIF(ABS(LAG(profit)" in text


def test_reference_file_contains_empty_with_prior_scenario(root):
    ref = (root / "docs" / "powerbi_reference_values.md").read_text()
    assert "| L |" in ref and "not -100%" in ref
