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


def test_maybe_display_skips_during_widget_change():
    rt = get_runtime()
    rt._executing_widget_change = True
    calls: list[object] = []

    def _fake_display(obj: object) -> None:
        calls.append(obj)

    original = widgets._try_import_display
    widgets._try_import_display = lambda: _fake_display  # type: ignore[assignment]
    try:
        widgets._maybe_display(handle=object())
    finally:
        widgets._try_import_display = original  # type: ignore[assignment]
        rt._executing_widget_change = False
    assert calls == []


def test_maybe_display_renders_on_initial_run():
    calls: list[object] = []

    def _fake_display(obj: object) -> None:
        calls.append(obj)

    original = widgets._try_import_display
    widgets._try_import_display = lambda: _fake_display  # type: ignore[assignment]
    try:
        handle = object()
        widgets._maybe_display(handle=handle)
    finally:
        widgets._try_import_display = original  # type: ignore[assignment]
    assert calls == [handle]


def _ipywidgets_or_skip():
    ipw = widgets._try_import_ipywidgets()
    if ipw is None:
        pytest.skip("ipywidgets not installed")
    return ipw


def test_button_rebuild_does_not_duplicate_click_handler():
    """Re-running a button cell must not stack additional on_click handlers.

    Regression for the runaway loop where each rerun added another handler, so a
    single user click eventually fanned out into many cascading reruns.
    """
    _ipywidgets_or_skip()
    rt = get_runtime()
    _new_cell()
    widgets.button(label="Go")
    handle = rt.widgets[0].handle
    initial_callbacks = len(handle._click_handlers.callbacks)
    for _ in range(5):
        rt._in_cell_counter = 0
        widgets.button(label="Go")
    assert len(handle._click_handlers.callbacks) == initial_callbacks


def test_select_rebuild_does_not_duplicate_observer():
    """Re-running a select cell must not stack additional value observers."""
    _ipywidgets_or_skip()
    rt = get_runtime()
    _new_cell()
    widgets.select(["A", "B", "C"], default="A")
    handle = rt.widgets[0].handle
    initial = len(handle._trait_notifiers.get("value", {}).get("change", []))
    for _ in range(5):
        rt._in_cell_counter = 0
        widgets.select(["A", "B", "C"], default="A")
    after = len(handle._trait_notifiers.get("value", {}).get("change", []))
    assert after == initial
