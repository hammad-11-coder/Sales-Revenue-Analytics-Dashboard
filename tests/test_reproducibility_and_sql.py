"""Reproducibility of the generator and executable verification of the SQL files."""
import hashlib

import pandas as pd

import generate_data
import verify_sql_against_python as vsp


def _hash_dir(path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.glob("*")) if p.is_file()}


def test_generator_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate_data.write_raw(a, 42)
    generate_data.write_raw(b, 42)
    assert _hash_dir(a) == _hash_dir(b)


def test_committed_raw_data_matches_generator(root, tmp_path):
    generate_data.write_raw(tmp_path, 42)
    assert _hash_dir(tmp_path) == _hash_dir(root / "data" / "raw")


def test_different_seed_gives_different_data(tmp_path):
    generate_data.write_raw(tmp_path / "s1", 1)
    generate_data.write_raw(tmp_path / "s2", 2)
    assert _hash_dir(tmp_path / "s1")["orders.csv"] != _hash_dir(tmp_path / "s2")["orders.csv"]


def test_sql_files_execute_and_match_pandas():
    results = vsp.run()
    failed = [f"{r.name}: {r.detail}" for r in results if not r.ok]
    assert not failed, failed
    assert len(results) >= 45


def test_sql_query_blocks_are_single_statements(root):
    for f in ("02_data_quality_checks.sql", "04_business_analysis.sql"):
        qs = vsp.named_queries((root / "sql" / f).read_text())
        assert qs and all(q.strip().upper().startswith(("SELECT", "WITH")) for q in qs.values())


def test_sql_uses_required_techniques(root):
    text = "\n".join((root / "sql" / f).read_text().upper() for f in
                     ("03_transformations.sql", "04_business_analysis.sql"))
    for token in ("WITH ", "ROW_NUMBER()", "RANK()", "LAG(", "NTILE(", "SUM(", "PARTITION BY", "LEFT JOIN",
                  "COUNT(DISTINCT", "NULLIF("):
        assert token in text, token


def test_sql_detects_injected_data_problems(root):
    """The quality-check SQL must actually catch bad data (a check that never fires proves nothing)."""
    con = vsp.load_sqlite(root / "data" / "processed")
    for s in vsp.split_statements((root / "sql" / "03_transformations.sql").read_text()):
        con.execute(s)
    con.execute("INSERT INTO order_items VALUES (999999, 'ORD-NOPE', 'P001', 0, -5, 1, 2.5)")
    con.execute("UPDATE orders SET ship_date = '2020-01-01' WHERE order_id = (SELECT MIN(order_id) FROM orders WHERE ship_date IS NOT NULL)")
    sql = vsp.named_queries((root / "sql" / "02_data_quality_checks.sql").read_text())["data_quality_violations"]
    dq = pd.read_sql_query(sql, con).set_index("check_name").violations
    for check in ("items_orphan_order", "items_nonpositive_quantity", "items_nonpositive_price",
                  "items_discount_out_of_range", "orders_ship_before_order"):
        assert dq[check] >= 1, check
