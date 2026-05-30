"""Tests for the Rust ``LiteralEventChainVar`` class.

`_native.RustLiteralEventChainVar` extends `RustLiteralVar` (mirroring
`LiteralEventChainVar(…, LiteralVar, EventChainVar)`). Its `create` renders the
chain JS via the Rust assembler and gathers the chain's var_data, byte-identical
to `LiteralVar.create(chain)` — `_js_expr` AND `_get_all_var_data()` — across the
event grammar, while being ~20-40x faster (no per-event Var-tree composition).
"""

from __future__ import annotations

import pytest
from reflex_compiler_rust import _native

import reflex as rx
from reflex.vars import LiteralVar


class _ECState(rx.State):
    count: int = 0

    def inc(self) -> None:
        self.count += 1

    def add(self, x: int, y: int) -> None:
        self.count += x + y


def _chain(component) -> object:
    """The on_click EventChain of a component.

    Args:
        component: The component to read the trigger from.

    Returns:
        The EventChain bound to on_click.
    """
    return component.event_triggers["on_click"]


def _vd(var) -> tuple:
    """Flatten a var's aggregate var_data for comparison.

    Args:
        var: The var to read var_data from.

    Returns:
        A (state, hooks, flattened-imports) tuple.
    """
    vd = var._get_all_var_data()
    if vd is None:
        return (None, (), ())
    return (
        vd.state,
        tuple(vd.hooks),
        tuple((lib, t.tag) for lib, ts in vd.imports for t in ts),
    )


def test_extends_literal_var() -> None:
    """RustLiteralEventChainVar subclasses RustLiteralVar (and RustVar)."""
    assert issubclass(_native.RustLiteralEventChainVar, _native.LiteralVar)
    assert issubclass(_native.RustLiteralEventChainVar, _native.Var)


CASES = {
    "single": lambda: _ECState.inc,
    "lit_args": lambda: _ECState.add(1, 2),
    "state_var_arg": lambda: _ECState.add(_ECState.count, 2),
    "multi": lambda: [_ECState.inc, _ECState.add(3, 4)],
    "multi_state_var": lambda: [_ECState.add(_ECState.count, 1), _ECState.inc],
    "redirect": lambda: rx.redirect("/home"),
}


@pytest.mark.parametrize("key", sorted(CASES))
def test_create_matches_python_js_and_var_data(key: str) -> None:
    """RustLiteralEventChainVar.create matches LiteralVar.create byte-for-byte."""
    chain = _chain(rx.button("x", on_click=CASES[key]()))
    py = LiteralVar.create(chain)
    ru = _native.RustLiteralEventChainVar.create(chain)
    assert ru._js_expr == str(py._js_expr)
    assert _vd(ru) == _vd(py)
    assert isinstance(ru, _native.LiteralVar)
