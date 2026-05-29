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


def _gather_bundle(chain) -> tuple:
    """Gather a chain into the primitive (arg_names, chain_ea, events) bundle.

    Args:
        chain: The EventChain.

    Returns:
        The primitive bundle the Rust bundle-assembler consumes.
    """
    from reflex.compiler.arena_record import (
        _arg_names,
        _event_handler_name,
        _render_event_value,
    )

    arg_names = _arg_names(chain.args_spec)
    chain_ea = [(k, _render_event_value(v)) for k, v in chain.event_actions.items()]
    events = [
        (
            _event_handler_name(es.handler),
            [(a[0]._js_expr, _render_event_value(a[1])) for a in es.args],
            [(k, _render_event_value(v)) for k, v in es.event_actions.items()],
        )
        for es in chain.events
    ]
    return arg_names, chain_ea, events


@pytest.mark.parametrize("key", sorted(CASES))
def test_rust_event_chain_bundle_matches_python(key: str) -> None:
    """The one-crossing bundle assembler matches the Python assembler too."""
    chain = _chain(CASES[key]())
    assert chain is not None
    expected = str(LiteralVar.create(chain)._js_expr)
    assert _native.rust_assemble_event_chain_bundle(*_gather_bundle(chain)) == expected
