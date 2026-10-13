"""Smoke tests for the optional Streamlit app using Streamlit's headless AppTest runner."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app" / "app.py")


def _run(setup=None):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    if setup:
        setup(at)
        at.run()
    return at


def _multiselect(at, label):
    return next(m for m in at.multiselect if m.label == label)


def test_default_view_renders_without_error():
    at = _run()
    assert not at.exception
    assert any("Sales & Revenue Analytics Dashboard" in t.value for t in at.title)


def test_year_filter_shows_comparison():
    at = _run(lambda a: _multiselect(a, "Year").set_value([2025]))
    assert not at.exception
    assert any("vs same period last year" in c.value for c in at.caption)


def test_single_month_compares_with_previous_month():
    def setup(a):
        _multiselect(a, "Year").set_value([2025])
        _multiselect(a, "Month").set_value(["October"])
    at = _run(setup)
    assert not at.exception
    assert any("vs previous month" in c.value for c in at.caption)


def test_empty_selection_is_handled():
    def setup(a):
        _multiselect(a, "Region").set_value(["Central"])
        _multiselect(a, "Product Category").set_value(["Apparel"])
        _multiselect(a, "Customer Segment").set_value(["Corporate"])
        _multiselect(a, "Year").set_value([2024])
        _multiselect(a, "Month").set_value(["January"])
    at = _run(setup)
    assert not at.exception
    assert any("No completed sales" in i.value for i in at.info)
