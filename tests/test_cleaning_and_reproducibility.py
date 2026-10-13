"""Cleaning-rule unit tests and end-to-end reproducibility (same seed -> byte-identical files)."""
import hashlib
from pathlib import Path

import pandas as pd
import pytest

import clean_data
import generate_data


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ reproducibility
@pytest.fixture(scope="module")
def regenerated(tmp_path_factory, root):
    out = tmp_path_factory.mktemp("repro")
    raw, proc = out / "raw", out / "processed"
    generate_data.write_raw(raw, seed=42)
    clean_data.run(raw, proc)
    return raw, proc


def test_raw_generation_is_reproducible(regenerated, root):
    raw, _ = regenerated
    for f in ["orders", "order_items", "customers", "products", "regions"]:
        assert _sha(raw / f"{f}.csv") == _sha(root / "data" / "raw" / f"{f}.csv"), f
    assert _sha(raw / "defect_manifest.json") == _sha(root / "data" / "raw" / "defect_manifest.json")


def test_cleaning_is_reproducible(regenerated, root):
    _, proc = regenerated
    for f in ["fact_sales", "orders", "order_items", "customers", "products", "dim_date", "cleaning_log", "rejected_rows"]:
        assert _sha(proc / f"{f}.csv") == _sha(root / "data" / "processed" / f"{f}.csv"), f


def test_different_seed_gives_different_data(tmp_path):
    generate_data.write_raw(tmp_path, seed=7)
    assert _sha(tmp_path / "orders.csv") != _sha(Path(__file__).resolve().parents[1] / "data" / "raw" / "orders.csv")


# ------------------------------------------------------------------ cleaning rules on crafted input
def test_parse_dates_accepts_three_formats():
    s = pd.Series(["2025-03-14", "14/03/2025", "14-Mar-2025", "garbage", None])
    parsed, non_iso = clean_data.parse_dates(s)
    assert list(parsed.iloc[:3]) == [pd.Timestamp("2025-03-14")] * 3
    assert parsed.iloc[3:].isna().all()
    assert list(non_iso) == [False, True, True, False, False]


def test_dayfirst_convention_is_used_for_slashes():
    parsed, _ = clean_data.parse_dates(pd.Series(["02/03/2025"]))
    assert parsed.iloc[0] == pd.Timestamp("2025-03-02")  # 2 March, not 3 February


def test_clean_items_rules():
    log = clean_data.CleaningLog()
    products = pd.DataFrame({"product_id": ["P001"], "unit_cost": [50.0]})
    raw = pd.DataFrame({
        "order_item_id": ["1", "2", "3", "4", "5", "6", "7", "8", "8"],
        "order_id": ["O1"] * 5 + ["O1", "ORPHAN", "O1", "O1"],
        "product_id": ["P001"] * 5 + ["P999", "P001", "P001", "P001"],
        "quantity": ["2", "0", "1", "1", "1", "1", "1", "1", "1"],
        "unit_price": ["100", "100", "-5", "100", "100", "100", "100", "100", "100"],
        "unit_cost": ["60", "60", "60", None, "60", "60", "60", "60", "60"],
        "discount": ["0.1", "0.1", "0.1", "0.1", "15", "0.1", "0.1", "150", "150"],
    })
    out = clean_data.clean_items(raw, {"O1"}, {"O1"}, products, log)
    assert sorted(out.order_item_id.astype(str)) == ["1", "4", "5"]
    row5 = out[out.order_item_id.astype(str) == "5"].iloc[0]
    assert row5.discount == pytest.approx(0.15)           # 15 -> 0.15
    row4 = out[out.order_item_id.astype(str) == "4"].iloc[0]
    assert row4.unit_cost == 50.0                          # imputed from product master
    counts = log.log_frame().set_index("rule_id").rows_affected
    assert counts["I1"] == 1 and counts["I2"] == 1 and counts["I3"] == 1
    assert counts["I5"] == 1 and counts["I4"] == 1 and counts["I8"] == 1 and counts["I7"] == 1
    assert counts["I6"] == 1                                 # 150 (> 100%) rejected


def test_orders_header_rules():
    log = clean_data.CleaningLog()
    customers = pd.DataFrame({"customer_id": ["C1"]})
    regions = pd.DataFrame({"region_id": [1]})
    raw = pd.DataFrame({
        "order_id": ["A", "B", "C", "D", "E"],
        "order_date": ["2025-01-05", "05/01/2025", "2025-01-05", "2027-01-01", "2025-01-05"],
        "ship_date": ["2025-01-07", "2025-01-01", None, "2027-01-02", "2025-01-06"],
        "customer_id": ["C1", "C1", "C1", "C1", None],
        "region_id": ["1"] * 5,
        "sales_channel": ["Online", None, "Online", "Online", "Online"],
        "order_status": ["COMPLETED", "Canceled", "Completed", "Completed", "Completed"],
    })
    out = clean_data.clean_orders_header(raw, customers, regions, log, "2024-01-01", "2025-12-31").set_index("order_id")
    assert sorted(out.index) == ["A", "B", "C"]            # D out of window, E missing customer
    assert out.loc["A", "order_status"] == "Completed"
    assert out.loc["B", "order_status"] == "Cancelled"      # 'Canceled' spelling normalised
    assert pd.isna(out.loc["B", "ship_date"])               # ship before order / cancelled -> NULL
    assert out.loc["B", "sales_channel"] == "Unknown"
    assert out.loc["B", "order_date"] == pd.Timestamp("2025-01-05")


def test_cleaning_never_drops_silently(root):
    """Every rejected record is quarantined with a rule id and reason."""
    rej = pd.read_csv(root / "data" / "processed" / "rejected_rows.csv")
    assert len(rej) > 0
    assert rej[["table", "rule_id", "reason", "record_key", "raw_record"]].notna().all().all()
    log = pd.read_csv(root / "data" / "processed" / "cleaning_log.csv")
    rejected_by_log = log[log.action == "rejected"].rows_affected.sum()
    assert rejected_by_log == len(rej)
