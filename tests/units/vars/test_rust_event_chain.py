"""Byte-parity gate for the Rust event-chain serializer.

`_native.rust_assemble_event_chain` moves `EventChain` -> JS rendering into
Rust. It must produce exactly what `LiteralVar.create(chain)._js_expr` does
across the event grammar: single/multi handlers, positional args, and special
client handlers (redirect). This pins that parity.
"""

from __future__ import annotations

import pytest
from reflex_compiler_rust import _native

import reflex as rx
from reflex.vars import LiteralVar


class _EvState(rx.State):
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
    return component.event_triggers.get("on_click")


CASES = {
    "single": lambda: rx.button("x", on_click=_EvState.inc),
    "with_args": lambda: rx.button("x", on_click=_EvState.add(1, 2)),
    "multi": lambda: rx.button("x", on_click=[_EvState.inc, _EvState.add(3, 4)]),
    "redirect": lambda: rx.button("x", on_click=rx.redirect("/home")),
}


@pytest.mark.parametrize("key", sorted(CASES))
def test_rust_event_chain_matches_python(key: str) -> None:
    """Rust event-chain JS is byte-identical to LiteralVar.create(chain)."""
    chain = _chain(CASES[key]())
    assert chain is not None
    expected = str(LiteralVar.create(chain)._js_expr)
    assert _native.rust_assemble_event_chain(chain) == expected
