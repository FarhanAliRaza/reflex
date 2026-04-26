"""Unit tests for the Zustand store + event-loop runtime templates.

Covers ``packages/reflex-base/src/reflex_base/compiler/zustand_template.py``.
The templates are pure-string codegen, so the assertions verify the
generated JS contains the right exports, hook names, and atomic update
shape (one ``set`` call per ``applyDelta``).
"""

from __future__ import annotations

from reflex_base.compiler.zustand_template import (
    color_mode_inline_setter_template,
    event_loop_runtime_template,
    zustand_store_template,
)


def test_zustand_store_template_imports_zustand():
    src = zustand_store_template()
    assert 'from "zustand"' in src or "from 'zustand'" in src
    assert "create" in src


def test_zustand_store_template_exposes_each_slice():
    src = zustand_store_template()
    for slice_name in ("state", "dispatch", "eventLoop", "uploads", "colorMode"):
        assert slice_name in src


def test_zustand_store_template_exposes_each_hook():
    src = zustand_store_template()
    for hook in (
        "useReflexStore",
        "useReflexState",
        "useReflexDispatch",
        "useReflexEventLoop",
        "useReflexUploads",
        "useReflexColorMode",
    ):
        assert f"export const {hook}" in src or f"export const {hook} =" in src


def test_zustand_store_template_atomic_apply_delta():
    """The applyDelta action must do exactly one set() call per delta."""
    src = zustand_store_template()
    # The applyDelta entry uses a single `set((prev) => ...)` — one set call,
    # one return — so subscribers see one commit per backend delta.
    apply_delta_section = src.split("applyDelta:")[1].split("setStateSlice")[0]
    assert apply_delta_section.count("set(") == 1


def test_zustand_store_template_imperative_accessors():
    src = zustand_store_template()
    for accessor in (
        "getReflexState",
        "getReflexDispatch",
        "applyReflexDelta",
        "setReflexEventLoop",
        "registerReflexDispatch",
    ):
        assert f"export const {accessor}" in src


def test_event_loop_runtime_template_imports_store():
    src = event_loop_runtime_template()
    assert "$/utils/store" in src
    assert "applyReflexDelta" in src
    assert "setReflexEventLoop" in src


def test_event_loop_runtime_template_exposes_set_adapter():
    src = event_loop_runtime_template()
    assert "setEventLoopAdapter" in src
    assert "getEventLoopAdapter" in src
    assert "dispatchEventChain" in src


def test_event_loop_runtime_template_no_react_import():
    """The runtime module is target-agnostic — it must not pull in React or React Router."""
    src = event_loop_runtime_template()
    assert 'from "react"' not in src
    assert "from 'react'" not in src
    assert "react-router" not in src


def test_color_mode_inline_setter_template_returns_function():
    src = color_mode_inline_setter_template()
    assert "export const colorModeInlineScript" in src
    assert "prefers-color-scheme: dark" in src
    assert "data-color-mode" in src


def test_color_mode_inline_setter_template_no_imports():
    """Inline head script must be self-contained — no module imports."""
    src = color_mode_inline_setter_template()
    assert "import " not in src
