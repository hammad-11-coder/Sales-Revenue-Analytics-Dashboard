"""Shared fixtures. Tests run against the committed data in data/raw and data/processed."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import kpi_definitions as kpi  # noqa: E402


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def tables():
    return kpi.load_processed(ROOT / "data" / "processed")


@pytest.fixture(scope="session")
def wide(tables):
    return kpi.enrich(tables["fact_sales"], tables)


@pytest.fixture(scope="session")
def calendar_keys(tables):
    return sorted(int(k) for k in tables["dim_date"]["month_key"].unique())
