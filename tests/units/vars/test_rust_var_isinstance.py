"""Parity gate for var membership over Rust-backed vars.

The rip unifies every typed ``Var`` into the Rust ``Var`` (carrying its type tag
in ``_var_type``). ``isinstance(x, Var)`` / ``isinstance(x, LiteralVar)`` are
*native* — the Rust ``Var`` / ``LiteralVar`` are registered virtual subclasses
of the Python bases (``MetaclassVar`` is an ``ABCMeta``), so no custom
``__instancecheck__`` bridge is involved. Typed-*category* membership
(``NumberVar`` / ``StringVar`` / …), which depends on a var's runtime
``_var_type`` rather than its class, is answered by :func:`var_isinstance`.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from reflex_base.vars.base import (
    ArrayVar,
    BooleanVar,
    LiteralNumberVar,
    LiteralStringVar,
    LiteralVar,
    NoneVar,
    NumberVar,
    ObjectVar,
    StringVar,
    Var,
    var_isinstance,
)
from reflex_base.vars.datetime import DateTimeVar
from reflex_compiler_rust._native import RustLiteralVar, RustVar

_NON_LITERAL_TARGETS = [
    NumberVar,
    BooleanVar,
    StringVar,
    ArrayVar,
    ObjectVar,
    DateTimeVar,
    NoneVar,
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
def test_var_isinstance_matches_guess_type(var_type: object, target: type) -> None:
    """``var_isinstance`` classifies a RustVar the same regardless of how it was
    built (direct vs guessed); every RustVar is natively a ``Var``."""
    guessed = Var(_js_expr="x", _var_type=var_type).guess_type()
    rust_var = RustVar("x", var_type, None)
    assert var_isinstance(rust_var, target) == var_isinstance(guessed, target)
    assert isinstance(rust_var, Var)


@pytest.mark.parametrize(
    ("var_type", "category"),
    [
        (int, NumberVar),
        (float, NumberVar),
        (bool, BooleanVar),
        (str, StringVar),
        (list[int], ArrayVar),
        (dict[str, int], ObjectVar),
        (type(None), NoneVar),
    ],
)
def test_var_isinstance_concrete(var_type: object, category: type) -> None:
    """A RustVar classifies (via ``var_isinstance``) as the expected category."""
    rust_var = RustVar("x", var_type, None)
    assert var_isinstance(rust_var, category)
    if category is not StringVar:
        assert not var_isinstance(rust_var, StringVar)


@pytest.mark.parametrize("value", [5, "hi", [1, 2], {"a": 1}, True, None])
def test_literal_native_isinstance(value: object) -> None:
    """A RustLiteralVar is natively a ``LiteralVar`` and a ``Var``."""
    rust_var = RustLiteralVar.create(value)
    assert isinstance(rust_var, LiteralVar)
    assert isinstance(rust_var, Var)


@pytest.mark.parametrize("target", [LiteralNumberVar, LiteralStringVar])
def test_literal_category_matches(target: type) -> None:
    """``var_isinstance`` for a literal target matches the Python literal var."""
    for value in (5, "hi"):
        python_var = LiteralVar.create(value)
        rust_var = RustLiteralVar.create(value)
        assert var_isinstance(rust_var, target) == var_isinstance(python_var, target)


def test_non_literal_rust_var_is_not_literal() -> None:
    """A plain (non-literal) RustVar is not a LiteralVar but is a Var."""
    assert not isinstance(RustVar("x", int, None), LiteralVar)
    assert isinstance(RustVar("x", int, None), Var)


def test_var_isinstance_classifies_number() -> None:
    """``var_isinstance`` classifies a guessed numeric var as ``NumberVar``."""
    number = Var(_js_expr="x", _var_type=int).guess_type()
    assert var_isinstance(number, NumberVar)
    assert isinstance(number, Var)
    assert not var_isinstance(number, StringVar)
