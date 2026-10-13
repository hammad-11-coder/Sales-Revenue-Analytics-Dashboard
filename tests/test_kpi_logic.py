"""Unit tests for the shared KPI definitions, including the edge cases listed in the project brief."""
import pandas as pd
import pytest

import kpi_definitions as kpi


def _frame(rows):
    cols = ["order_id", "customer_id", "order_status", "line_revenue", "line_cost", "line_profit", "month_key"]
    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------ safe division and growth
def test_safe_div_handles_zero_and_missing():
    assert kpi.safe_div(10, 4) == 2.5
    assert kpi.safe_div(10, 0) is None
    assert kpi.safe_div(None, 4) is None
    assert kpi.safe_div(4, None) is None
    assert kpi.safe_div(float("nan"), 4) is None


def test_pct_change_handles_zero_and_missing_previous():
    assert kpi.pct_change(110, 100) == pytest.approx(0.10)
    assert kpi.pct_change(90, 100) == pytest.approx(-0.10)
    assert kpi.pct_change(5, 0) is None
    assert kpi.pct_change(5, None) is None


# ------------------------------------------------------------------ KPI edge cases
def test_empty_selection_returns_zeros_and_none_ratios():
    k = kpi.compute_kpis(_frame([]))
    assert k["revenue"] == 0 and k["orders"] == 0 and k["customers"] == 0
    assert k["margin"] is None and k["aov"] is None


def test_zero_revenue_gives_no_margin_or_aov():
    k = kpi.compute_kpis(_frame([["O1", "C1", "Completed", 0.0, 0.0, 0.0, 202501]]))
    assert k["revenue"] == 0
    assert k["margin"] is None          # 0 / 0 must be undefined, not 0% and not an error
    assert k["aov"] == 0.0              # one completed order with zero value: 0 / 1


def test_negative_profit_is_reported_not_hidden():
    k = kpi.compute_kpis(_frame([["O1", "C1", "Completed", 100.0, 130.0, -30.0, 202501]]))
    assert k["profit"] == -30.0
    assert k["margin"] == pytest.approx(-0.30)


def test_only_completed_orders_count():
    rows = [["O1", "C1", "Completed", 100.0, 60.0, 40.0, 202501],
            ["O2", "C2", "Cancelled", 500.0, 300.0, 200.0, 202501],
            ["O3", "C3", "Returned", 700.0, 400.0, 300.0, 202501]]
    k = kpi.compute_kpis(_frame(rows))
    assert (k["revenue"], k["orders"], k["customers"], k["placed_orders"]) == (100.0, 1, 1, 3)
    assert k["cancellation_rate"] == pytest.approx(1 / 3) and k["return_rate"] == pytest.approx(1 / 3)


def test_orders_are_distinct_not_line_counts():
    rows = [["O1", "C1", "Completed", 50.0, 30.0, 20.0, 202501]] * 3 + [["O2", "C1", "Completed", 10.0, 5.0, 5.0, 202501]]
    k = kpi.compute_kpis(_frame(rows))
    assert k["orders"] == 2 and k["customers"] == 1
    assert k["aov"] == pytest.approx(160.0 / 2)


# ------------------------------------------------------------------ month arithmetic and comparison
def test_shift_month_key_crosses_year_boundaries():
    assert kpi.shift_month_key(202501, -1) == 202412
    assert kpi.shift_month_key(202412, 1) == 202501
    assert kpi.shift_month_key(202503, -12) == 202403
    assert kpi.shift_month_key(202401, -1) == 202312


def test_single_month_compares_with_previous_month(calendar_keys):
    p = kpi.comparison_plan([202510], calendar_keys)
    assert p["mode"] == "MoM" and p["prior_keys"] == [202509] and p["available"]


def test_january_compares_with_december_of_previous_year(calendar_keys):
    p = kpi.comparison_plan([202501], calendar_keys)
    assert p["prior_keys"] == [202412] and p["available"]


def test_first_month_has_no_comparison(calendar_keys):
    p = kpi.comparison_plan([202401], calendar_keys)
    assert not p["available"] and p["prior_keys"] is None


def test_multi_month_selection_compares_with_same_months_last_year(calendar_keys):
    p = kpi.comparison_plan([202501, 202502, 202503], calendar_keys)
    assert p["mode"] == "YoY" and p["prior_keys"] == [202401, 202402, 202403]


def test_full_first_year_has_no_comparison(calendar_keys):
    assert not kpi.comparison_plan(list(range(202401, 202413)), calendar_keys)["available"]


def test_partial_prior_period_is_not_used(calendar_keys):
    # Two Marches selected: the 2024 March has no 2023 counterpart, so no comparison at all.
    assert not kpi.comparison_plan([202403, 202503], calendar_keys)["available"]


def test_empty_month_selection(calendar_keys):
    p = kpi.comparison_plan([], calendar_keys)
    assert p["mode"] == "NONE" and not p["available"]


def test_kpis_with_comparison_values(wide, calendar_keys):
    r = kpi.kpis_with_comparison(wide, list(range(202501, 202513)), calendar_keys)
    cur, prev = r["current"], r["previous"]
    assert prev is not None
    assert r["change"]["revenue"] == pytest.approx(cur["revenue"] / prev["revenue"] - 1)
    assert r["change"]["margin_pp"] == pytest.approx((cur["margin"] - prev["margin"]) * 100)


def test_kpis_with_comparison_unavailable_gives_none_changes(wide, calendar_keys):
    r = kpi.kpis_with_comparison(wide, list(range(202401, 202413)), calendar_keys)
    assert r["previous"] is None
    assert all(v is None for v in r["change"].values())


def test_period_values_do_not_double_count(wide, calendar_keys):
    """Sum of the two years equals the all-time total (partition property)."""
    y24 = kpi.kpis_with_comparison(wide, list(range(202401, 202413)), calendar_keys)["current"]
    y25 = kpi.kpis_with_comparison(wide, list(range(202501, 202513)), calendar_keys)["current"]
    allt = kpi.compute_kpis(wide)
    assert y24["revenue"] + y25["revenue"] == pytest.approx(allt["revenue"], abs=0.01)
    assert y24["orders"] + y25["orders"] == allt["orders"]


# ------------------------------------------------------------------ rankings under filters
def test_top_n_rankings_change_with_filters(wide):
    done = wide[wide.order_status == "Completed"]
    all_top = done.groupby("product_name").line_revenue.sum().nlargest(10).index.tolist()
    east = done[done.region == "East"].groupby("product_name").line_revenue.sum().nlargest(10).index.tolist()
    assert len(all_top) == len(east) == 10
    assert all_top != east


def test_top_5_customers_are_sorted_and_unique(wide):
    done = wide[wide.order_status == "Completed"]
    top = done.groupby("customer_id").line_revenue.sum().nlargest(5)
    assert top.is_monotonic_decreasing and len(top) == 5


def test_month_sort_is_chronological(tables):
    d = tables["dim_date"].drop_duplicates("month_key").sort_values("month_key")
    labels = list(d.month_label)
    assert labels[0] == "Jan 2024" and labels[-1] == "Dec 2025" and len(labels) == 24


# ------------------------------------------------------------------ formatting
def test_format_inr_compact_and_full():
    assert kpi.format_inr(12_345_678) == "₹1.23 Cr"
    assert kpi.format_inr(560_000) == "₹5.60 L"
    assert kpi.format_inr(9_999) == "₹9,999"
    assert kpi.format_inr(1_234_567, compact=False) == "₹12,34,567"
    assert kpi.format_inr(-250_000) == "-₹2.50 L"
    assert kpi.format_inr(None) == "–"


def test_format_pct():
    assert kpi.format_pct(0.1234) == "12.3%"
    assert kpi.format_pct(None) == "–"
    assert kpi.format_pct(0.05, signed=True) == "+5.0%"
