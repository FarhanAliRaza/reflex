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

from tests.units.vars._var_corpus import _record

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
