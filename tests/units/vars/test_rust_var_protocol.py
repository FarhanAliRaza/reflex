"""Parity gate for the Rust ``Var`` base protocol against the Python ``Var``.

The rip replaces the Python ``Var`` with ``_native.RustVar``. Beyond rendering
(covered by ``test_rust_var_literal``), the framework leans on ``Var``'s base
protocol: ``_replace`` / ``_without_data`` / ``_var_state`` / ``guess_type`` /
``bool`` / ``is_none`` / ``is_not_none`` / ``_var_set_state`` / ``to_string`` /
``js_type`` / ``_as_ref`` / ``__deepcopy__`` / ``__iter__`` / ``__contains__``.

Each test builds the same input with the Python ``Var`` and the Rust ``RustVar``
and asserts the protocol method produces a byte-identical result (``_js_expr``,
``_var_type``, and the aggregate ``_get_all_var_data()``). The Python ``Var`` is
the oracle until it is deleted.
"""

from __future__ import annotations

import copy

import pytest
from reflex_base.utils import imports
from reflex_base.utils.exceptions import VarTypeError
from reflex_base.vars.base import Var, VarData
from reflex_compiler_rust._native import RustLiteralVar, RustVar, RustVarData

_IMPORTS = {"$/foo": [imports.ImportVar(tag="bar")]}


def _py(js: str = "state.count", t: type = int, *, stateful: bool = False) -> Var:
    vd = (
        VarData(state="my_state", field_name="count", imports=_IMPORTS)
        if stateful
        else None
    )
    return Var(_js_expr=js, _var_type=t, _var_data=vd)


def _rust(js: str = "state.count", t: type = int, *, stateful: bool = False) -> RustVar:
    vd = (
        RustVarData(state="my_state", field_name="count", imports=_IMPORTS)
        if stateful
        else None
    )
    return RustVar(js, t, vd)


def _assert_same(py_var, rust_var) -> None:
    """Assert a Python Var and a RustVar render to the identical record."""
    assert rust_var._js_expr == py_var._js_expr
    assert rust_var._var_type == py_var._var_type
    assert rust_var._get_all_var_data() == py_var._get_all_var_data()


@pytest.mark.parametrize("stateful", [False, True])
def test_to_string_json(stateful: bool) -> None:
    """``to_string()`` wraps in ``JSON.stringify`` and keeps self's var_data."""
    _assert_same(
        _py(stateful=stateful).to_string(),
        _rust(stateful=stateful).to_string(),
    )


@pytest.mark.parametrize("stateful", [False, True])
def test_to_string_prototype(stateful: bool) -> None:
    """``to_string(use_json=False)`` uses the ``toString`` arrow."""
    _assert_same(
        _py(stateful=stateful).to_string(use_json=False),
        _rust(stateful=stateful).to_string(use_json=False),
    )


@pytest.mark.parametrize("stateful", [False, True])
def test_js_type(stateful: bool) -> None:
    """``js_type()`` renders ``(typeof(...))`` and keeps self's var_data."""
    _assert_same(_py(stateful=stateful).js_type(), _rust(stateful=stateful).js_type())


@pytest.mark.parametrize("stateful", [False, True])
def test_as_ref(stateful: bool) -> None:
    """``_as_ref()`` renders ``refs[...]`` with only the ``refs`` import."""
    _assert_same(_py(stateful=stateful)._as_ref(), _rust(stateful=stateful)._as_ref())


def test_deepcopy_returns_self() -> None:
    """Vars are immutable, so ``deepcopy`` returns the same object."""
    v = _rust()
    assert copy.deepcopy(v) is v


def test_iter_raises() -> None:
    """Iterating a Var raises ``VarTypeError`` with the same message."""
    with pytest.raises(VarTypeError) as py_exc:
        iter(_py())
    with pytest.raises(VarTypeError) as rust_exc:
        iter(_rust())
    assert str(rust_exc.value) == str(py_exc.value)


def test_contains_raises() -> None:
    """``in`` on a Var raises ``VarTypeError`` with the same message."""
    with pytest.raises(VarTypeError) as py_exc:
        _ = 1 in _py()
    with pytest.raises(VarTypeError) as rust_exc:
        _ = 1 in _rust()
    assert str(rust_exc.value) == str(py_exc.value)


@pytest.mark.parametrize("stateful", [False, True])
def test_without_data(stateful: bool) -> None:
    """``_without_data()`` strips the var_data, keeping js/type."""
    _assert_same(
        _py(stateful=stateful)._without_data(), _rust(stateful=stateful)._without_data()
    )


@pytest.mark.parametrize("stateful", [False, True])
def test_var_state(stateful: bool) -> None:
    """``_var_state`` returns the enclosing state name."""
    assert _rust(stateful=stateful)._var_state == _py(stateful=stateful)._var_state


def test_bool() -> None:
    """``bool()`` wraps in ``isTrue(...)`` with the import multiplicity."""
    _assert_same(_py(stateful=True).bool(), _rust(stateful=True).bool())


def test_is_not_none() -> None:
    """``is_not_none()`` wraps in ``isNotNullOrUndefined(...)``."""
    _assert_same(_py(stateful=True).is_not_none(), _rust(stateful=True).is_not_none())


def test_is_none() -> None:
    """``is_none()`` negates ``is_not_none()``."""
    _assert_same(_py(stateful=True).is_none(), _rust(stateful=True).is_none())


@pytest.mark.parametrize(
    "js",
    ["5", "state.count", '"hi"', "[1, 2]"],
)
def test_decode_raw(js: str) -> None:
    """``_decode()`` JSON-parses the expr, falling back to the raw string."""
    assert RustVar(js, int, None)._decode() == Var(_js_expr=js, _var_type=int)._decode()


@pytest.mark.parametrize("value", [5, "hi", [1, 2], {"a": 1}, True, None])
def test_decode_literal(value: object) -> None:
    """``LiteralVar._decode()`` returns the stored value."""
    assert RustLiteralVar.create(value)._decode() == value


def test_create_passthrough() -> None:
    """``Var.create(var)`` returns the same var object."""
    v = _rust()
    assert RustVar.create(v) is v


def test_create_literal() -> None:
    """``Var.create(value)`` builds a literal var."""
    c = RustVar.create(5)
    assert c._js_expr == "5"
    assert c._decode() == 5
