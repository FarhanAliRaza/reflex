"""Parity gate for the ``isinstance`` bridge over Rust-backed vars.

The rip replaces every typed ``Var`` subclass (``NumberVar`` / ``StringVar`` /
…) with the unified ``RustVar``, which carries its type tag in ``_var_type``.
``MetaclassVar.__instancecheck__`` bridges this: ``isinstance(rust_var,
NumberVar)`` must behave exactly like ``isinstance(python_var.guess_type(),
NumberVar)``. These tests assert that equivalence across the type lattice, plus
the ``LiteralVar`` discrimination (a non-literal ``RustVar`` is not a
``LiteralVar``).
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from reflex_base.vars.base import LiteralVar, NoneVar, Var
from reflex_base.vars.datetime import DateTimeVar
from reflex_base.vars.number import BooleanVar, LiteralNumberVar, NumberVar
from reflex_base.vars.object import ObjectVar
from reflex_base.vars.sequence import ArrayVar, LiteralStringVar, StringVar
from reflex_compiler_rust._native import RustLiteralVar, RustVar

_NON_LITERAL_TARGETS = [
    Var,
    NumberVar,
    BooleanVar,
    StringVar,
    ArrayVar,
    ObjectVar,
    DateTimeVar,
    NoneVar,
    LiteralVar,
]

_TYPES = [
    int,
    float,
    bool,
    str,
    list[int],
    dict[str, int],
    type(None),
    datetime.datetime,
    Any,
    int | None,
    list,
    dict,
    tuple[int, ...],
]


@pytest.mark.parametrize("var_type", _TYPES)
@pytest.mark.parametrize("target", _NON_LITERAL_TARGETS)
def test_isinstance_matches_guess_type(var_type: object, target: type) -> None:
    """A RustVar's isinstance result matches the Python var's guessed type."""
    python_var = Var(_js_expr="x", _var_type=var_type).guess_type()
    rust_var = RustVar("x", var_type, None)
    assert isinstance(rust_var, target) == isinstance(python_var, target)


_LITERAL_TARGETS = [
    LiteralVar,
    LiteralNumberVar,
    LiteralStringVar,
    NumberVar,
    StringVar,
    Var,
]


@pytest.mark.parametrize("value", [5, "hi", [1, 2], {"a": 1}, True, None])
@pytest.mark.parametrize("target", _LITERAL_TARGETS)
def test_literal_isinstance_matches(value: object, target: type) -> None:
    """A RustLiteralVar's isinstance result matches the Python literal var."""
    python_var = LiteralVar.create(value)
    rust_var = RustLiteralVar.create(value)
    assert isinstance(rust_var, target) == isinstance(python_var, target)


def test_non_literal_rust_var_is_not_literal() -> None:
    """A plain (non-literal) RustVar is not a LiteralVar."""
    assert not isinstance(RustVar("x", int, None), LiteralVar)
    assert isinstance(RustVar("x", int, None), Var)


def test_python_var_isinstance_unaffected() -> None:
    """The bridge does not change isinstance for Python var instances."""
    python_number = Var(_js_expr="x", _var_type=int).guess_type()
    assert isinstance(python_number, NumberVar)
    assert isinstance(python_number, Var)
    assert not isinstance(python_number, StringVar)
