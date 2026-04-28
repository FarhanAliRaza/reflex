"""Tests for the public ``rx.notebook`` namespace and module-level ``__call__``."""

from __future__ import annotations

import reflex as rx
from reflex.notebook.runtime import NotebookRuntime


def test_module_is_callable_and_returns_runtime():
    runtime = rx.notebook()  # type: ignore[operator]
    assert isinstance(runtime, NotebookRuntime)


def test_module_exposes_phase1_primitives():
    expected = {
        "select",
        "slider",
        "text_input",
        "checkbox",
        "date_picker",
        "file_upload",
        "button",
        "row",
        "display",
        "deploy",
        "view_source",
        "init",
    }
    assert expected.issubset(set(dir(rx.notebook)))


def test_view_source_returns_python_source():
    rx.notebook(reset=True)  # type: ignore[operator]
    source = rx.notebook.view_source(app_name="demo", print_source=False)
    assert "import reflex as rx" in source
    assert "class State(rx.State):" in source
