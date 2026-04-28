"""Tests for the layout primitives (row + vertical-stacking default)."""

from __future__ import annotations

from reflex.notebook import layout
from reflex.notebook.runtime import get_runtime


def test_row_returns_items_unchanged():
    get_runtime().record_cell("c", cell_id="c1")
    assert layout.row("a", "b", "c") == ("a", "b", "c")


def test_row_records_layout_output():
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    layout.row(1, "two", 3.0)
    outputs = rt.outputs
    assert len(outputs) == 1
    assert outputs[0].kind == "row"
    assert outputs[0].repr_hint == "primitive,primitive,primitive"


def test_row_with_no_items():
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    assert layout.row() == ()
    assert rt.outputs[0].kind == "row"
