"""Gate for the scalar ``LiteralVar.create`` -> Rust cutover.

Non-string scalars (``int``/``float``/``bool``/``None``) created via the public
``LiteralVar.create`` now produce the Rust-backed literal var. These tests pin
the observable behavior of that cutover: the produced type, byte-identical
rendering (including the ``1.0`` / ``Infinity`` / ``NaN`` float edge cases), the
``json()`` contract, and the operator type-validation that the typed Python
``Var`` classes enforced (so invalid operations still raise and valid ones still
render).
"""

from __future__ import annotations

import math
import operator

import pytest
from reflex_base.utils.exceptions import PrimitiveUnserializableToJSONError
from reflex_base.vars.base import LiteralVar, Var
from reflex_compiler_rust._native import RustLiteralVar


@pytest.mark.parametrize("value", [5, -7, 0, 1.5, 1.0, 100.0, True, False, None])
def test_scalar_create_returns_rust_literal(value: object) -> None:
    """Non-string scalars route to the Rust literal var."""
    assert isinstance(LiteralVar.create(value), RustLiteralVar)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1.0"),
        (100.0, "100.0"),
        (1.5, "1.5"),
        (5, "5"),
        (True, "true"),
        (None, "null"),
    ],
)
def test_scalar_rendering(value: object, expected: str) -> None:
    """Scalar rendering is byte-identical to the historical Python output."""
    assert str(LiteralVar.create(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(math.inf, "Infinity"), (-math.inf, "-Infinity"), (math.nan, "NaN")],
)
def test_non_finite_float_rendering(value: float, expected: str) -> None:
    """inf/nan render as their JS globals and raise on json()."""
    var = LiteralVar.create(value)
    assert str(var) == expected
    with pytest.raises(PrimitiveUnserializableToJSONError):
        var.json()


def test_scalar_json() -> None:
    """Finite scalar json() round-trips through json.dumps."""
    assert LiteralVar.create(5).json() == "5"
    assert LiteralVar.create(1.5).json() == "1.5"
    assert LiteralVar.create(True).json() == "true"


@pytest.mark.parametrize(
    "op",
    [
        operator.add,
        operator.sub,
        operator.truediv,
        operator.floordiv,
        operator.mod,
        operator.pow,
    ],
)
def test_number_op_with_non_number_raises(op) -> None:
    """A numeric var operation against a non-number raises (both directions)."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        op(number, array)
    with pytest.raises(TypeError):
        op(array, number)


@pytest.mark.parametrize("op", [operator.lt, operator.le, operator.gt, operator.ge])
def test_number_comparison_with_non_number_raises(op) -> None:
    """Ordering a numeric var against a non-number raises."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        op(number, array)


def test_number_times_array_repeats() -> None:
    """``number * array`` stays valid (array repeat), same as ``array * number``."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    expected = "Array.from({ length: 5 }).flatMap(() => [1, 2])"
    assert str(number * array) == expected
    assert str(array * number) == expected


def test_strict_float_array_repeat_raises() -> None:
    """A strict-float count cannot repeat an array."""
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        _ = LiteralVar.create(1.5) * array


def test_number_arithmetic_still_works() -> None:
    """Number-number arithmetic renders unchanged."""
    five = LiteralVar.create(5)
    assert str(five + LiteralVar.create(3)) == "(5 + 3)"
    assert str(five > LiteralVar.create(3)) == "(5 > 3)"


def test_var_create_scalar_is_rust() -> None:
    """The public ``Var.create`` also routes scalars to Rust."""
    assert isinstance(Var.create(5), RustLiteralVar)
