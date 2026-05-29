"""Parity gate for the Rust ``Var`` — scalar-literal slice.

This is the first byte-parity proof of the Var cutover: the Rust-backed
``Var`` (``_native.RustVar``, built via ``rust_literal`` / ``rust_raw_var``)
must render the exact ``_js_expr`` / ``_var_type`` / ``_get_all_var_data()``
the Python ``Var`` froze in the golden oracle for the scalar subset
(``lit_*`` + ``raw_var``).

As later slices land (operators, typed subclasses, state/var_data, casting)
this file grows to cover them, until the Rust ``Var`` passes the *whole* golden
corpus and the Python implementation can be deleted. Until then it pins the
slice that is already done so it cannot regress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from reflex_compiler_rust import _native

from tests.units.vars._var_corpus import _GoldenState, _record, _type_name

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
# var_data propagation is the *next* slice, so these assert js_expr + var_type
# only. The Rust leaf is seeded from the Python state var's js_expr/type, so
# the operator rendering is what's under test (not state-name mangling). Each
# entry maps a golden key to a builder over the seeded Rust leaves.
def _num() -> object:
    """A Rust int leaf seeded from the Python state var.

    Returns:
        A RustVar mirroring ``_GoldenState.count``.
    """
    leaf = _GoldenState.count
    return _native.rust_raw_var(leaf._js_expr, leaf._var_type)


def _ratio() -> object:
    """A Rust float leaf seeded from the Python state var.

    Returns:
        A RustVar mirroring ``_GoldenState.ratio``.
    """
    leaf = _GoldenState.ratio
    return _native.rust_raw_var(leaf._js_expr, leaf._var_type)


def _flag() -> object:
    """A Rust bool leaf seeded from the Python state var.

    Returns:
        A RustVar mirroring ``_GoldenState.flag``.
    """
    leaf = _GoldenState.flag
    return _native.rust_raw_var(leaf._js_expr, leaf._var_type)


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
def test_rust_operator_renders_golden(key: str, golden: dict) -> None:
    """A Rust operator renders the golden js_expr + var_type (var_data next)."""
    rust_var = OPERATOR_CASES[key]()
    assert rust_var._js_expr == golden[key]["js_expr"]
    assert _type_name(rust_var._var_type) == golden[key]["var_type"]
