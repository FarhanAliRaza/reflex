"""Tests for the Rust ``LiteralVar`` class (`_native.RustLiteralVar`).

`RustLiteralVar` is the Rust analog of Python's `LiteralVar(Var)`: it *extends*
`RustVar` (inheriting `_js_expr` / `_var_type` / `_get_all_var_data` / every
operator) and adds `_var_value` plus a `create` classmethod that dispatches a
Python value to a literal var, byte-identical to `LiteralVar.create`.
"""

from __future__ import annotations

import pytest
from reflex_compiler_rust import _native

import reflex as rx
from reflex.vars import LiteralVar


class _LVState(rx.State):
    count: int = 0


def test_is_class_extending_rust_var() -> None:
    """RustLiteralVar is a class that subclasses RustVar (like LiteralVar(Var))."""
    assert isinstance(_native.RustLiteralVar, type)
    assert issubclass(_native.RustLiteralVar, _native.RustVar)


def test_create_returns_literal_var_instance() -> None:
    """create() returns a RustLiteralVar that is also a RustVar."""
    v = _native.RustLiteralVar.create(5)
    assert isinstance(v, _native.RustLiteralVar)
    assert isinstance(v, _native.RustVar)
    assert v._js_expr == "5"
    assert v._var_type is int
    assert v._var_value == 5


def test_inherits_var_operators() -> None:
    """A RustLiteralVar uses the inherited RustVar operators."""
    assert (_native.RustLiteralVar.create(5) + 1)._js_expr == "(5 + 1)"


def test_create_passes_through_existing_var() -> None:
    """create(Var) returns the Var unchanged (matches LiteralVar.create)."""
    leaf = _LVState.count
    assert _native.RustLiteralVar.create(leaf) is leaf


PARITY_VALUES = [
    5,
    -7,
    1.5,
    "hi",
    'a"b',
    True,
    False,
    None,
    [1, 2, 3],
    {"a": 1, "b": 2},
    {"a": {"b": 1}},
]


@pytest.mark.parametrize("value", PARITY_VALUES)
def test_create_matches_python_literal_var(value: object) -> None:
    """RustLiteralVar.create renders byte-identically to LiteralVar.create."""
    assert _native.RustLiteralVar.create(value)._js_expr == str(
        LiteralVar.create(value)._js_expr
    )
