"""Executes sql/02-04 on SQLite and reconciles every result with independently computed pandas figures.

SQLite is the engine available to the tests; sql/01_create_schema.sql (MySQL DDL / LOAD DATA) is not executed here.
"""
import pytest

import verify_sql_against_python as v


@pytest.fixture(scope="module")
def results():
    return v.run()


def test_sql_scripts_execute_and_match_pandas(results):
    failed = [f"{r.name}: {r.detail}" for r in results if not r.ok]
    assert not failed, "\n".join(failed)


def test_every_named_query_was_exercised(results, root):
    names = {r.name for r in results}
    for f in ("02_data_quality_checks.sql", "04_business_analysis.sql"):
        for q in v.named_queries((root / "sql" / f).read_text()):
            assert f"{f}:{q} executes" in names


def test_mysql_reserved_word_not_used_as_identifier(root):
    import re
    for p in (root / "sql").glob("*.sql"):
        code = re.sub(r"--.*$", "", p.read_text().lower(), flags=re.M)   # ignore comments
        assert "year_month" not in code, p.name
