"""Parity gate for the Rust ``Var`` against the golden oracle.

Byte-parity proof of the Var cutover so far: the Rust-backed ``Var``
(``_native.RustVar``) must reproduce the exact ``_js_expr`` / ``_var_type`` /
``_get_all_var_data()`` the Python ``Var`` froze in the golden oracle. Every
case asserts the **full record** (including the var_data merge and the exact
import multiplicity Python produces); operator/method leaves are seeded from
the Python state var (``rust_from_python_var``) so composition is what's under
test, not state-name mangling. Covered:

* scalar literals (``lit_*``) + raw vars;
* number/boolean/comparison operators (``num_*`` / ``bool_*``);
* string methods + casting (``str_*`` / ``to_*``);
* array + object methods (``arr_*`` / ``obj_*``).

The remaining corpus surface — the f-string marker protocol (``fstr_*``) — and
then the typed-subclass facades land next, after which the Rust ``Var`` passes
the whole golden corpus and the Python implementation can be deleted. Until
then this pins what is already done so it cannot regress.
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


# --- string-method + casting slice ---
# String methods compose on the same doubling var_op primitive Python uses
# (length = split().length(); mul = (split() * n).join()), so the import
# multiplicity (2/4/8/16) falls out by construction. Casting keeps js_expr +
# var_data and only changes var_type.
def _name() -> object:
    """A Rust str leaf mirroring ``_GoldenState.name`` (with var_data).

    Returns:
        A RustVar equivalent to ``_GoldenState.name``.
    """
    return _native.rust_from_python_var(_GoldenState.name)


STRING_CASES = {
    "str_add": lambda: _name() + "!",
    "str_radd": lambda: "hello " + _name(),
    "str_mul": lambda: _name() * 2,
    "str_lower": lambda: _name().lower(),
    "str_upper": lambda: _name().upper(),
    "str_capitalize": lambda: _name().capitalize(),
    "str_length": lambda: _name().length(),
    "str_contains": lambda: _name().contains("a"),
    "str_startswith": lambda: _name().startswith("a"),
    "str_split": lambda: _name().split(","),
    "str_getitem": lambda: _name()[0],
    "to_str": lambda: _num().to(str),
    "to_int": lambda: _native.rust_raw_var("x", object).to(int),
    "to_bool": lambda: _native.rust_raw_var("x", object).to(bool),
}


@pytest.mark.parametrize("key", sorted(OPERATOR_CASES))
def test_rust_operator_matches_golden(key: str, golden: dict) -> None:
    """A Rust operator reproduces the golden record byte-for-byte.

    Asserts the full _record (js_expr + var_type + var_data), so the var_data
    merge / import multiplicity is validated alongside the rendering.
    """
    assert _record(OPERATOR_CASES[key]()) == golden[key]


@pytest.mark.parametrize("key", sorted(STRING_CASES))
def test_rust_string_and_cast_matches_golden(key: str, golden: dict) -> None:
    """A Rust string method / cast reproduces the golden record byte-for-byte."""
    assert _record(STRING_CASES[key]()) == golden[key]


# --- array + object method slice ---
# Item access uses element/value type from var_type.__args__; concat unions the
# two array types via Python's `|`. Methods compose on the same var_op
# primitives, so the import multiplicity matches.
def _items() -> object:
    """A Rust list[int] leaf mirroring ``_GoldenState.items``.

    Returns:
        A RustVar equivalent to ``_GoldenState.items``.
    """
    return _native.rust_from_python_var(_GoldenState.items)


def _words() -> object:
    """A Rust list[str] leaf mirroring ``_GoldenState.words``.

    Returns:
        A RustVar equivalent to ``_GoldenState.words``.
    """
    return _native.rust_from_python_var(_GoldenState.words)


def _data() -> object:
    """A Rust dict[str, int] leaf mirroring ``_GoldenState.data``.

    Returns:
        A RustVar equivalent to ``_GoldenState.data``.
    """
    return _native.rust_from_python_var(_GoldenState.data)


CONTAINER_CASES = {
    "arr_length": lambda: _items().length(),
    "arr_getitem": lambda: _items()[0],
    "arr_contains": lambda: _items().contains(1),
    "arr_reverse": lambda: _items().reverse(),
    "arr_join": lambda: _words().join(","),
    "arr_concat": lambda: (
        _items() + _native.rust_raw_var("[4, 5]", _GoldenState.items._var_type)
    ),
    "obj_getitem": lambda: _data()["a"],
    "obj_getattr": lambda: _data().a,
    "obj_keys": lambda: _data().keys(),
    "obj_values": lambda: _data().values(),
    "obj_contains": lambda: _data().contains("a"),
}


@pytest.mark.parametrize("key", sorted(CONTAINER_CASES))
def test_rust_container_matches_golden(key: str, golden: dict) -> None:
    """A Rust array/object method reproduces the golden record byte-for-byte."""
    assert _record(CONTAINER_CASES[key]()) == golden[key]


# --- f-string marker protocol slice ---
# A RustVar formatted into a Python f-string emits a <reflex.Var> marker (and
# registers itself); rust_create_string decodes the assembled string back into
# a ConcatVarOperation. This exercises both directions of the protocol.
FSTRING_CASES = {
    "fstr_simple": lambda: _native.rust_create_string(f"v={_num()}"),
    "fstr_multi": lambda: _native.rust_create_string(f"{_name()}={_num()}"),
    "fstr_nested_op": lambda: _native.rust_create_string(f"sum={_num() + 1}"),
}


@pytest.mark.parametrize("key", sorted(FSTRING_CASES))
def test_rust_fstring_matches_golden(key: str, golden: dict) -> None:
    """A Rust f-string (format -> marker -> decode) matches the golden record."""
    assert _record(FSTRING_CASES[key]()) == golden[key]


LEAF_CASES = {
    "state_int": lambda: _GoldenState.count,
    "state_float": lambda: _GoldenState.ratio,
    "state_str": lambda: _GoldenState.name,
    "state_bool": lambda: _GoldenState.flag,
    "state_list": lambda: _GoldenState.items,
    "state_dict": lambda: _GoldenState.data,
}


@pytest.mark.parametrize("key", sorted(LEAF_CASES))
def test_seeded_leaf_matches_golden(key: str, golden: dict) -> None:
    """A leaf seeded from a Python state var reproduces its golden record.

    Covers every typed state leaf (int/float/str/bool/list/dict), confirming
    rust_from_python_var carries js_expr, var_type, and var_data faithfully.
    """
    assert _record(_native.rust_from_python_var(LEAF_CASES[key]())) == golden[key]
