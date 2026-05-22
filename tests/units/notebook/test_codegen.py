"""Tests for the Reflex source codegen."""

from __future__ import annotations

import ast

from reflex.notebook import widgets
from reflex.notebook.codegen import generate_app_source
from reflex.notebook.outputs import display
from reflex.notebook.runtime import get_runtime


def _populate_runtime() -> None:
    rt = get_runtime()
    rt.record_cell("input cell", cell_id="c1")
    widgets.select(["A", "B", "C"], default="A", label="Category")
    widgets.slider(0, 10, default=5, label="Threshold")
    rt.record_cell("output cell", cell_id="c2")
    display({"a": 1})


def test_generate_app_source_is_valid_python():
    _populate_runtime()
    source = generate_app_source(get_runtime(), app_name="my_app")
    ast.parse(source)


def test_generate_app_source_contains_state_fields():
    _populate_runtime()
    source = generate_app_source(get_runtime(), app_name="my_app")
    assert "class State(rx.State):" in source
    assert "category" in source
    assert "threshold" in source


def test_generate_app_source_contains_event_handlers():
    _populate_runtime()
    source = generate_app_source(get_runtime(), app_name="my_app")
    assert "def set_category(self" in source
    assert "def set_threshold(self" in source


def test_generate_app_source_contains_index_page():
    _populate_runtime()
    source = generate_app_source(get_runtime(), app_name="my_app")
    assert "def index() -> rx.Component:" in source
    assert "rx.vstack(" in source
    assert "app = rx.App()" in source
    assert "app.add_page(index, title='my_app')" in source


def test_generate_app_source_handles_empty_runtime():
    source = generate_app_source(get_runtime(), app_name="empty")
    ast.parse(source)
    assert "class State(rx.State):" in source
    assert "pass" in source


def test_generate_app_source_unique_field_names_for_repeated_labels():
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    widgets.select(["A", "B"], label="X")
    widgets.select(["C", "D"], label="X")
    source = generate_app_source(rt, app_name="dup")
    ast.parse(source)
    assert source.count("def set_x(") == 1
    assert "def set_x_2(" in source


def test_generate_app_source_slider_wraps_value_in_list():
    """Radix Slider.value expects a Sequence, so codegen must wrap the float Var."""
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    widgets.slider(0, 100, default=50, label="Threshold")
    source = generate_app_source(rt, app_name="s")
    ast.parse(source)
    assert "value=[State.threshold]" in source
    assert "def set_threshold(self, value: list[float])" in source
    assert "self.threshold = value[0]" in source


def test_generated_slider_compiles_as_reflex_component():
    """Run the generated module and instantiate the page to catch type-level errors."""
    import types

    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    widgets.slider(0, 100, default=50, label="Threshold")
    source = generate_app_source(rt, app_name="slider_check")
    module = types.ModuleType("slider_check_generated")
    exec(compile(source, "<generated>", "exec"), module.__dict__)
    component = module.index()
    assert component is not None
