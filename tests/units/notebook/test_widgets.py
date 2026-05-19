"""Tests for the input widget primitives.

These tests run without ipywidgets installed (the default in CI), so they verify the
Streamlit-style return-value behavior and the runtime registration but not interactive UI.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from reflex.notebook import widgets
from reflex.notebook.runtime import get_runtime


def _new_cell(cell_id: str = "c1") -> None:
    get_runtime().record_cell("body", cell_id=cell_id)


def test_select_returns_default():
    _new_cell()
    assert widgets.select(["A", "B", "C"], "B", label="X") == "B"


def test_select_first_option_when_no_default():
    _new_cell()
    assert widgets.select(["A", "B", "C"]) == "A"


def test_select_invalid_default_falls_back_to_first():
    _new_cell()
    assert widgets.select(["A", "B"], default="Z") == "A"


def test_select_requires_options():
    _new_cell()
    with pytest.raises(ValueError):
        widgets.select([])


def test_slider_clamps_default():
    _new_cell()
    assert widgets.slider(0, 10, default=20) == 10
    _new_cell("c2")
    assert widgets.slider(0, 10, default=-5) == 0


def test_slider_validates_range():
    _new_cell()
    with pytest.raises(ValueError):
        widgets.slider(min=10, max=0)


def test_text_input_returns_default():
    _new_cell()
    assert widgets.text_input("hello") == "hello"


def test_checkbox_returns_default():
    _new_cell()
    assert widgets.checkbox(True) is True


def test_date_picker_defaults_to_today():
    _new_cell()
    today = _dt.date.today()
    assert widgets.date_picker() == today


def test_file_upload_returns_none_initially():
    _new_cell()
    assert widgets.file_upload(label="Upload") is None


def test_button_returns_false_initially():
    _new_cell()
    assert widgets.button(label="Go") is False


def test_widgets_in_same_cell_get_unique_keys():
    _new_cell()
    widgets.select(["A", "B"], label="A")
    widgets.select(["X", "Y"], label="B")
    rt = get_runtime()
    keys = [w.key for w in rt.widgets]
    assert len(set(keys)) == 2


def test_widget_value_persists_across_recreation():
    _new_cell()
    widgets.select(["A", "B", "C"], default="A", label="X")
    rt = get_runtime()
    key = rt.widgets[0].key
    rt.update_widget_value(key, "C")
    rt._in_cell_counter = 0
    assert widgets.select(["A", "B", "C"], default="A", label="X") == "C"
