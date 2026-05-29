"""Parity gate for the Rust ``Var`` — scalars, operators, and var_data.

Byte-parity proof of the Var cutover so far: the Rust-backed ``Var``
(``_native.RustVar``) must reproduce the exact ``_js_expr`` / ``_var_type`` /
``_get_all_var_data()`` the Python ``Var`` froze in the golden oracle. Covered:

* scalar literals (``lit_*``) + raw vars, via ``rust_literal`` / ``rust_raw_var``;
* every number/boolean/comparison operator (``num_*`` / ``bool_*``), composed
  over a leaf seeded from the Python state var (``rust_from_python_var``) so the
  full record — including the var_data merge and the exact import multiplicity
  Python produces — is asserted.

As later slices land (typed subclasses, string/array/object methods, casting,
the f-string marker protocol) this file grows to cover them, until the Rust
``Var`` passes the *whole* golden corpus and the Python implementation can be
deleted. Until then it pins what is already done so it cannot regress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from reflex_compiler_rust import _native

from tests.units.vars._var_corpus import _GoldenState, _record

GOLDEN_PATH = Path(__file__).resolve().parent / "var_golden.json"

# The golden keys this slice currently reproduces, with the Python value each
# Rust literal is built from. Grows as the Rust Var grows.
SCALAR_CASES: dict[str, object] = {
    "lit_int": 5,
    "lit_neg_int": -7,
    "lit_float": 1.5,
    "lit_str": "hi",
    "lit_str_quote": 'a"b',
    "lit_bool_true": True,
    "lit_bool_false": False,
    "lit_none": None,
}


@pytest.fixture(scope="module")
def golden() -> dict:
    """Load the frozen golden output.

    Returns:
        The parsed golden fixture mapping.
    """
    return json.loads(GOLDEN_PATH.read_text())


@pytest.mark.parametrize("key", sorted(SCALAR_CASES))
def test_rust_literal_matches_golden(key: str, golden: dict) -> None:
    """A Rust scalar literal renders byte-identically to the Python golden."""
    rust_var = _native.rust_literal(SCALAR_CASES[key])
    assert _record(rust_var) == golden[key]


def test_rust_raw_var_matches_golden(golden: dict) -> None:
    """A Rust raw var (explicit js_expr + type) matches the Python golden."""
    rust_var = _native.rust_raw_var("x", int)
    assert _record(rust_var) == golden["raw_var"]


# --- operator slice ---
# The Rust leaf is seeded from the Python state var (js_expr + type + var_data)
# via rust_from_python_var, so operator *composition* is what's under test (not
# state-name mangling). These assert the full _record — js_expr, var_type, AND
# var_data (including the exact import multiplicity Python produces).
def _num() -> object:
    """A Rust int leaf mirroring ``_GoldenState.count`` (with var_data).

    Returns:
        A RustVar equivalent to ``_GoldenState.count``.
    """
    return _native.rust_from_python_var(_GoldenState.count)


def _ratio() -> object:
    """A Rust float leaf mirroring ``_GoldenState.ratio`` (with var_data).

    Returns:
        A RustVar equivalent to ``_GoldenState.ratio``.
    """
    return _native.rust_from_python_var(_GoldenState.ratio)


def _flag() -> object:
    """A Rust bool leaf mirroring ``_GoldenState.flag`` (with var_data).

    Returns:
        A RustVar equivalent to ``_GoldenState.flag``.
    """
    return _native.rust_from_python_var(_GoldenState.flag)


OPERATOR_CASES = {
    "num_add": lambda: _num() + 1,
    "num_radd": lambda: 1 + _num(),
    "num_sub": lambda: _num() - 2,
    "num_rsub": lambda: 10 - _num(),
    "num_mul": lambda: _num() * 3,
    "num_truediv": lambda: _num() / 2,
    "num_floordiv": lambda: _num() // 2,
    "num_mod": lambda: _num() % 5,
    "num_pow": lambda: _num() ** 2,
    "num_neg": lambda: -_num(),
    "num_abs": lambda: abs(_num()),
    "num_gt": lambda: _num() > 0,
    "num_ge": lambda: _num() >= 1,
    "num_lt": lambda: _num() < 5,
    "num_le": lambda: _num() <= 5,
    "num_eq": lambda: _num() == 3,
    "num_ne": lambda: _num() != 3,
    "num_nested": lambda: (_num() + 1) * 2 > 4,
    "num_float_add": lambda: _ratio() + 0.5,
    "bool_invert": lambda: ~_flag(),
    "bool_and": lambda: _flag() & (_num() > 0),
    "bool_or": lambda: _flag() | (_num() > 0),
}


@pytest.mark.parametrize("key", sorted(OPERATOR_CASES))
def test_rust_operator_matches_golden(key: str, golden: dict) -> None:
    """A Rust operator reproduces the golden record byte-for-byte.

    Asserts the full _record (js_expr + var_type + var_data), so the var_data
    merge / import multiplicity is validated alongside the rendering.
    """
    assert _record(OPERATOR_CASES[key]()) == golden[key]


def test_seeded_leaf_matches_golden(golden: dict) -> None:
    """A leaf seeded from a Python state var reproduces its golden record."""
    assert (
        _record(_native.rust_from_python_var(_GoldenState.count)) == golden["state_int"]
    )
