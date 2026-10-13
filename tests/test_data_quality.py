"""Data-quality, reproducibility, KPI-logic and SQL-reconciliation tests.

Run from the repository root:  python -m pytest tests -q
"""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

import clean_data
import generate_data
import kpi_definitions as kpi
import validate_data
import verify_sql_against_python as vsp


# ------------------------------------------------------------------ validate_data (78 checks)
def test_all_validation_checks_pass(root):
    checks = validate_data.run_checks(root / "data" / "processed", root / "data" / "raw")
    failed = [f"{c.group}: {c.name} ({c.detail})" for c in checks if not c.passed]
    assert not failed, failed
    assert len(checks) >= 70


# ------------------------------------------------------------------ keys and domains (independent of validate_data)
def test_primary_keys_unique(tables):
    for name, col in [("regions", "region_id"), ("products", "product_id"), ("customers", "customer_id"),
                      ("orders", "order_id"), ("order_items", "order_item_id"), ("fact_sales", "order_item_id")]:
        assert tables[name][col].is_unique, f"{name}.{col} not unique"


def test_foreign_keys_resolve(tables):
    t = tables
    assert t["orders"].customer_id.isin(t["customers"].customer_id).all()
    assert t["orders"].region_id.isin(t["regions"].region_id).all()
    assert t["order_items"].order_id.isin(t["orders"].order_id).all()
    assert t["order_items"].product_id.isin(t["products"].product_id).all()
    assert t["fact_sales"].order_date.isin(t["dim_date"].full_date).all()


def test_no_invalid_values(tables):
    i = tables["order_items"]
    assert (i.quantity > 0).all() and (i.unit_price > 0).all() and (i.unit_cost > 0).all()
    assert i.discount.between(0, 1).all()
    o = tables["orders"]
    assert o.order_status.isin(kpi.ORDER_STATUSES).all()
    shipped = o.dropna(subset=["ship_date"])
    assert (shipped.ship_date >= shipped.order_date).all()


def test_dataset_is_at_least_24_months(tables):
    assert tables["orders"].order_date.dt.to_period("M").nunique() >= 24


def test_calendar_is_continuous(tables):
    d = tables["dim_date"].full_date
    assert (d.diff().dropna() == pd.Timedelta(days=1)).all()
    months = sorted(tables["dim_date"].month_key.unique())
    assert all(kpi.shift_month_key(a, 1) == b for a, b in zip(months, months[1:]))


def test_month_label_sorts_by_month_key(tables):
    m = tables["dim_date"].drop_duplicates("month_key").sort_values("month_key")
    assert m.month_label.is_unique
    assert list(pd.to_datetime(m.month_label, format="%b %Y")) == sorted(pd.to_datetime(m.month_label, format="%b %Y"))


# ------------------------------------------------------------------ reconciliation
def test_revenue_cost_profit_reconcile_to_lines(tables, wide):
    items = tables["order_items"].merge(tables["orders"][["order_id", "order_status"]], on="order_id")
    done = items[items.order_status == "Completed"]
    rev = (done.quantity * done.unit_price * (1 - done.discount)).round(2).sum()
    cost = (done.quantity * done.unit_cost).round(2).sum()
    k = kpi.compute_kpis(wide)
    assert k["revenue"] == pytest.approx(rev, abs=0.01)
    assert k["cost"] == pytest.approx(cost, abs=0.01)
    assert k["profit"] == pytest.approx(rev - cost, abs=0.01)
    assert k["margin"] == pytest.approx((rev - cost) / rev)


def test_orders_are_not_double_counted(wide, tables):
    k = kpi.compute_kpis(wide)
    done_lines = int((wide.order_status == "Completed").sum())
    n_done = int((tables["orders"].order_status == "Completed").sum())
    assert k["orders"] == n_done
    assert done_lines > k["orders"]  # one order has several lines: a row count would overstate orders


def test_breakdowns_sum_to_total(wide):
    total = kpi.compute_kpis(wide)["revenue"]
    done = wide[wide.order_status == "Completed"]
    for col in ("region", "category", "segment", "month_key", "sales_channel", "product_id"):
        assert done.groupby(col).line_revenue.sum().sum() == pytest.approx(total, abs=0.01), col


def test_status_partition(wide, tables):
    k = kpi.compute_kpis(wide)
    assert k["placed_orders"] == len(tables["orders"])
    assert k["orders"] + k["cancelled_orders"] + k["returned_orders"] == k["placed_orders"]


# ------------------------------------------------------------------ KPI edge cases
def test_safe_div_and_pct_change_handle_zero_and_missing():
    assert kpi.safe_div(5, 0) is None
    assert kpi.safe_div(None, 3) is None
    assert kpi.safe_div(6, 3) == 2
    assert kpi.pct_change(5, 0) is None
    assert kpi.pct_change(5, None) is None
    assert kpi.pct_change(110, 100) == pytest.approx(0.10)
    assert kpi.pct_change(0, 100) == pytest.approx(-1.0)


def test_empty_selection_returns_zero_and_none_not_error(wide):
    k = kpi.compute_kpis(wide.iloc[0:0])
    assert k["revenue"] == 0 and k["orders"] == 0 and k["customers"] == 0
    assert k["margin"] is None and k["aov"] is None


def test_zero_revenue_slice_gives_none_margin(wide):
    row = wide[wide.order_status == "Completed"].iloc[[0]].copy()
    row["line_revenue"] = 0.0
    row["line_profit"] = -row["line_cost"]
    k = kpi.compute_kpis(row)
    assert k["revenue"] == 0 and k["margin"] is None


def test_negative_profit_is_preserved(wide):
    row = wide[wide.order_status == "Completed"].iloc[[0]].copy()
    row["line_revenue"], row["line_cost"] = 100.0, 150.0
    row["line_profit"] = -50.0
    k = kpi.compute_kpis(row)
    assert k["profit"] == -50.0 and k["margin"] == pytest.approx(-0.5)
    assert kpi.format_inr(-50.0) == "-₹50"


def test_cancelled_and_returned_excluded_from_revenue(wide):
    non_done = wide[wide.order_status != "Completed"]
    assert len(non_done) > 0
    assert kpi.compute_kpis(non_done)["revenue"] == 0.0
    assert kpi.compute_kpis(non_done)["margin"] is None


def test_real_empty_combination_exists_and_is_handled(wide):
    done = wide[wide.order_status == "Completed"]
    d = done[(done.region == "Central") & (done.category == "Apparel") & (done.segment == "Corporate") & (done.month_key == 202401)]
    assert d.empty
    k = kpi.compute_kpis(d)
    assert k["revenue"] == 0 and k["margin"] is None


# ------------------------------------------------------------------ month arithmetic and comparison plan
def test_shift_month_key_across_years():
    assert kpi.shift_month_key(202501, -1) == 202412
    assert kpi.shift_month_key(202412, 1) == 202501
    assert kpi.shift_month_key(202503, -12) == 202403
    assert kpi.shift_month_key(202401, -12) == 202301


def test_comparison_plan_modes(calendar_keys):
    p = kpi.comparison_plan([202510], calendar_keys)
    assert (p["mode"], p["prior_keys"], p["available"]) == ("MoM", [202509], True)
    p = kpi.comparison_plan([202501], calendar_keys)
    assert p["prior_keys"] == [202412]  # crosses the year boundary
    p = kpi.comparison_plan(range(202501, 202513), calendar_keys)
    assert p["mode"] == "YoY" and p["prior_keys"] == list(range(202401, 202413))


def test_comparison_blank_when_prior_outside_calendar(calendar_keys):
    assert kpi.comparison_plan([202401], calendar_keys)["available"] is False       # no Dec 2023
    assert kpi.comparison_plan(range(202401, 202413), calendar_keys)["available"] is False
    assert kpi.comparison_plan(calendar_keys, calendar_keys)["available"] is False  # all 24 months
    assert kpi.comparison_plan([202403, 202503], calendar_keys)["available"] is False  # partial prior
    assert kpi.comparison_plan([], calendar_keys)["mode"] == "NONE"


def test_month_over_month_values(wide, calendar_keys):
    r = kpi.kpis_with_comparison(wide, [202510], calendar_keys)
    sept = kpi.compute_kpis(wide[wide.month_key == 202509])
    assert r["previous"]["revenue"] == pytest.approx(sept["revenue"])
    assert r["change"]["revenue"] == pytest.approx(r["current"]["revenue"] / sept["revenue"] - 1)


def test_year_over_year_values(wide, calendar_keys):
    r = kpi.kpis_with_comparison(wide, list(range(202501, 202513)), calendar_keys)
    y24 = kpi.compute_kpis(wide[wide.cal_year == 2024])
    assert r["previous"]["revenue"] == pytest.approx(y24["revenue"])
    assert r["change"]["margin_pp"] == pytest.approx((r["current"]["margin"] - y24["margin"]) * 100)


def test_selected_year_does_not_break_prior_period(wide, calendar_keys):
    """Prior period must come from outside the selected months (the DAX REMOVEFILTERS concern)."""
    r = kpi.kpis_with_comparison(wide, [202506, 202507], calendar_keys)
    assert r["plan"]["prior_keys"] == [202406, 202407]
    assert r["previous"]["revenue"] > 0


# ------------------------------------------------------------------ Top-N under filters
def test_top_n_rankings_respond_to_filters(wide):
    done = wide[wide.order_status == "Completed"]
    all_top = done.groupby("product_name").line_revenue.sum().nlargest(10).index.tolist()
    east = done[done.region == "East"]
    east_top = east.groupby("product_name").line_revenue.sum().nlargest(10)
    assert len(east_top) == 10 and east_top.index.tolist() != all_top
    assert east_top.is_monotonic_decreasing
    cust5 = east.groupby("customer_id").line_revenue.sum().nlargest(5)
    assert len(cust5) == 5 and cust5.is_monotonic_decreasing
    assert set(cust5.index) != set(done.groupby("customer_id").line_revenue.sum().nlargest(5).index)


def test_not_every_category_is_assumed_profitable_but_margins_are_sane(wide):
    done = wide[wide.order_status == "Completed"]
    m = done.groupby("category").apply(lambda d: d.line_profit.sum() / d.line_revenue.sum(), include_groups=False)
    assert m.min() < 0.05 and m.max() > 0.4   # real spread: thin-margin and high-margin categories both exist
    loss_products = done.groupby("product_id").line_profit.sum()
    assert (loss_products < 0).any()          # the loss-making highlight has something to highlight


# ------------------------------------------------------------------ formatting
@pytest.mark.parametrize("value,compact,expected", [
    (265860607.2, True, "₹26.59 Cr"), (1234567, True, "₹12.35 L"), (5600, True, "₹5,600"),
    (2397344, False, "₹23,97,344"), (999, False, "₹999"), (None, True, "–"), (-1500000, True, "-₹15.00 L"),
])
def test_format_inr(value, compact, expected):
    assert kpi.format_inr(value, compact) == expected


def test_format_pct():
    assert kpi.format_pct(0.1234) == "12.3%" and kpi.format_pct(None) == "–"
    assert kpi.format_pct(0.05, signed=True) == "+5.0%"


# ------------------------------------------------------------------ reproducibility
def _digest(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()


def test_generation_is_reproducible_with_fixed_seed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ma = generate_data.write_raw(a, seed=11)
    mb = generate_data.write_raw(b, seed=11)
    assert ma == mb
    for name in ("orders", "order_items", "customers", "products", "regions"):
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes(), name


def test_different_seed_changes_data(tmp_path):
    generate_data.write_raw(tmp_path / "a", seed=11)
    generate_data.write_raw(tmp_path / "b", seed=12)
    assert (tmp_path / "a" / "order_items.csv").read_bytes() != (tmp_path / "b" / "order_items.csv").read_bytes()


def test_committed_raw_matches_seed_42(root):
    """The committed data/raw files are exactly what seed 42 generates."""
    manifest = json.loads((root / "data" / "raw" / "defect_manifest.json").read_text())
    assert manifest["seed"] == 42
    truth = generate_data.build_truth(42)
    assert {k: len(v) for k, v in truth.items()} == manifest["truth_rows"]


def test_committed_raw_files_are_byte_identical_to_a_fresh_seed_42_run(root, tmp_path):
    generate_data.write_raw(tmp_path, seed=42)
    for name in ("orders", "order_items", "customers", "products", "regions"):
        assert (tmp_path / f"{name}.csv").read_bytes() == (root / "data" / "raw" / f"{name}.csv").read_bytes(), name
    assert (tmp_path / "defect_manifest.json").read_text() == (root / "data" / "raw" / "defect_manifest.json").read_text()


def test_committed_processed_files_are_byte_identical_to_a_fresh_clean(root, tmp_path):
    clean_data.run(root / "data" / "raw", tmp_path)
    for f in sorted(p.name for p in (root / "data" / "processed").iterdir()):
        assert (tmp_path / f).read_bytes() == (root / "data" / "processed" / f).read_bytes(), f


def test_pipeline_end_to_end_on_fresh_seed(tmp_path):
    """generate -> clean -> validate on a different seed: the cleaning rules find every injected defect."""
    raw, out = tmp_path / "raw", tmp_path / "processed"
    generate_data.write_raw(raw, seed=5)
    clean_data.run(raw, out)
    checks = validate_data.run_checks(out, raw)
    failed = [f"{c.name} ({c.detail})" for c in checks if not c.passed]
    assert not failed, failed


def test_clean_is_idempotent_on_processed_output(tmp_path, root):
    """Cleaning already-clean data must change nothing and reject nothing."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for n in ("regions", "products", "customers", "orders", "order_items"):
        (raw / f"{n}.csv").write_bytes((root / "data" / "processed" / f"{n}.csv").read_bytes())
    s = clean_data.run(raw, tmp_path / "out")
    assert s["rows_rejected_total"] == 0
    assert s["rows_clean"]["orders"] == len(pd.read_csv(root / "data" / "processed" / "orders.csv"))


# ------------------------------------------------------------------ cleaning rules on crafted bad data
def _craft_raw(tmp_path, root, mutate):
    raw = tmp_path / "raw"
    raw.mkdir()
    d = {n: pd.read_csv(root / "data" / "processed" / f"{n}.csv", dtype=str) for n in
         ("regions", "products", "customers", "orders", "order_items")}
    mutate(d)
    for n, df in d.items():
        df.to_csv(raw / f"{n}.csv", index=False)
    clean_data.run(raw, tmp_path / "out")
    return pd.read_csv(tmp_path / "out" / "cleaning_log.csv").set_index("rule_id").rows_affected


def test_cleaning_rejects_bad_quantity_price_discount(tmp_path, root):
    def mutate(d):
        i = d["order_items"]
        i.loc[0, "quantity"] = "0"
        i.loc[1, "quantity"] = "-3"
        i.loc[2, "unit_price"] = "-10"
        i.loc[3, "unit_price"] = ""
        i.loc[4, "discount"] = "-0.2"
        i.loc[5, "discount"] = "150"
    log = _craft_raw(tmp_path, root, mutate)
    assert log["I2"] == 2 and log["I3"] == 2 and log["I6"] == 2


def test_cleaning_handles_orphans_missing_keys_and_impossible_dates(tmp_path, root):
    def mutate(d):
        d["order_items"].loc[0, "product_id"] = "P999"
        d["order_items"].loc[1, "order_id"] = "ORD-NOPE-1"
        d["orders"].loc[2, "customer_id"] = ""
        d["orders"].loc[3, "order_date"] = "2031-01-01"
        d["orders"].loc[4, "order_date"] = "not a date"
        d["orders"].loc[5, "ship_date"] = "2000-01-01"
    log = _craft_raw(tmp_path, root, mutate)
    assert log["I8"] == 1 and log["I7"] == 1
    assert log["O5a"] == 1 and log["O2d"] == 1 and log["O2c"] == 1 and log["O4"] == 1


def test_parse_dates_formats():
    s = pd.Series(["2025-03-04", "04/03/2025", "04-Mar-2025", "garbage", None])
    parsed, non_iso = clean_data.parse_dates(s)
    assert parsed.iloc[0] == parsed.iloc[1] == parsed.iloc[2] == pd.Timestamp("2025-03-04")
    assert parsed.iloc[3:].isna().all()
    assert non_iso.tolist() == [False, True, True, False, False]


# ------------------------------------------------------------------ SQL vs pandas
def test_sql_scripts_match_pandas(root):
    results = vsp.run(root / "data" / "processed", root / "sql")
    failed = [f"{r.name}: {r.detail}" for r in results if not r.ok]
    assert not failed, failed
    assert len(results) >= 45


def test_sql_files_contain_required_techniques(root):
    text = "\n".join((root / "sql" / f).read_text().upper() for f in
                     ("03_transformations.sql", "04_business_analysis.sql"))
    for token in ("WITH ", "ROW_NUMBER()", "RANK()", "NTILE(", "LAG(", "OVER (PARTITION BY", "COUNT(DISTINCT", "LEFT JOIN", "NULLIF("):
        assert token in text, token
    assert "01_create_schema.sql" in {p.name for p in (root / "sql").iterdir()}
    ddl = (root / "sql" / "01_create_schema.sql").read_text().upper()
    for token in ("PRIMARY KEY", "FOREIGN KEY", "CHECK (", "LOAD DATA"):
        assert token in ddl, token


# ------------------------------------------------------------------ repository hygiene
def test_required_files_exist(root):
    required = [
        "README.md", "LICENSE", ".gitignore", "data/README.md", "excel/data_cleaning_guide.md",
        "sql/01_create_schema.sql", "sql/02_data_quality_checks.sql", "sql/03_transformations.sql", "sql/04_business_analysis.sql",
        "python/generate_data.py", "python/validate_data.py", "python/exploratory_analysis.ipynb", "python/requirements.txt",
        "powerbi/DAX_Measures.md", "powerbi/Data_Model.md", "powerbi/PowerBI_Build_Guide.md",
        "docs/data_dictionary.md", "docs/business_rules.md", "docs/project_architecture.md",
        "tests/test_data_quality.py", "streamlit_app/app.py", "streamlit_app/requirements.txt",
        "data/raw/orders.csv", "data/raw/order_items.csv", "data/raw/customers.csv", "data/raw/products.csv", "data/raw/regions.csv",
        "data/processed/fact_sales.csv", "data/processed/dim_date.csv", "data/processed/cleaning_log.csv",
    ]
    missing = [p for p in required if not (root / p).exists()]
    assert not missing, missing
    assert any((root / "dashboard_screenshots").glob("*.png"))


def test_no_machine_specific_paths_or_secrets(root):
    import re
    patterns = [r"/home/[a-z_][\w-]*/", r"/tmp/claude", r"C:\\Users", r"[\w.+-]+@[\w-]+\.[a-z]{2,}", r"password\s*="]
    offenders = []
    for p in root.rglob("*"):
        if (p.is_file() and p.suffix in {".py", ".md", ".sql", ".json", ".txt", ".ipynb"}
                and not {".pytest_cache", "__pycache__"} & set(p.parts) and p.name != "test_data_quality.py"):
            text = p.read_text(errors="ignore")
            offenders += [f"{p.relative_to(root)}: {m.group(0)}" for pat in patterns for m in [re.search(pat, text)] if m]
    assert not offenders, offenders


def test_synthetic_disclosure_in_key_docs(root):
    for f in ("README.md", "data/README.md", "docs/data_dictionary.md", "powerbi/DAX_Measures.md"):
        assert "synthetic" in (root / f).read_text().lower(), f
