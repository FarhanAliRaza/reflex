"""Byte-parity spec for the cheap event-chain assembler.

Event-chain rendering via ``LiteralVar.create(chain)._js_expr`` is the
gather path's dominant cost (~110us/chain — it builds a composed Var graph)
even though the raw pieces are ~0.2us to read. ``_assemble_event_chain``
reads those raw pieces (handler name, each arg's cached ``_js_expr``,
``event_actions``, arg-names) and string-assembles the JS in ~7us — 16x
faster.

This suite pins that assembler across the full event grammar: every case
asserts it is **byte-identical** to ``LiteralVar.create(chain)._js_expr`` —
no-args, literal & reactive & expr & multi args, event_actions
(stop_propagation / prevent_default), multi-handler block form, value/blur
arg-specs, lambda, and special events (set / redirect / console_log /
call_script / noop).
"""

from __future__ import annotations

import pytest
from reflex_base.vars.base import LiteralVar

import reflex as rx
from reflex.compiler.arena_record import _assemble_event_chain


class _EvState(rx.State):
    n: int = 0
    name: str = "x"

    def inc(self) -> None:
        self.n += 1

    def inc_by(self, x: int) -> None:
        self.n += x

    def two_args(self, a: int, b: str) -> None:
        self.n += a

    def set_name(self, v: str) -> None:
        self.name = v


def _expected(component, trigger: str) -> str:
    chain = component.event_triggers[trigger]
    return str(LiteralVar.create(chain)._js_expr)


# (label, component factory, trigger) — spanning the whole render grammar.
_CASES = {
    "no_args": (lambda: rx.button("x", on_click=_EvState.inc), "on_click"),
    "int_arg": (lambda: rx.button("x", on_click=_EvState.inc_by(5)), "on_click"),
    "str_arg": (
        lambda: rx.button("x", on_click=_EvState.set_name("hi")),
        "on_click",
    ),
    "var_arg": (
        lambda: rx.button("x", on_click=_EvState.inc_by(_EvState.n)),
        "on_click",
    ),
    "expr_arg": (
        lambda: rx.button("x", on_click=_EvState.inc_by(_EvState.n + 1)),
        "on_click",
    ),
    "two_args": (
        lambda: rx.button("x", on_click=_EvState.two_args(3, "y")),
        "on_click",
    ),
    "stop_propagation": (
        lambda: rx.button("x", on_click=_EvState.inc.stop_propagation),
        "on_click",
    ),
    "prevent_default": (
        lambda: rx.button("x", on_click=_EvState.inc.prevent_default),
        "on_click",
    ),
    "two_handlers": (
        lambda: rx.button("x", on_click=[_EvState.inc, _EvState.inc_by(2)]),
        "on_click",
    ),
    "three_handlers": (
        lambda: rx.button(
            "x", on_click=[_EvState.inc, _EvState.inc, _EvState.inc_by(1)]
        ),
        "on_click",
    ),
    "on_change_value_spec": (
        lambda: rx.input(on_change=_EvState.set_name),
        "on_change",
    ),
    "on_blur": (lambda: rx.input(on_blur=_EvState.set_name), "on_blur"),
    "lambda_handler": (
        lambda: rx.button("x", on_click=lambda: _EvState.inc()),
        "on_click",
    ),
    "special_redirect": (
        lambda: rx.button("x", on_click=rx.redirect("/somewhere")),
        "on_click",
    ),
    "special_console_log": (
        lambda: rx.button("x", on_click=rx.console_log("hello")),
        "on_click",
    ),
    "special_set_value": (
        lambda: rx.button("x", on_click=rx.set_value("field", "")),
        "on_click",
    ),
    "special_noop": (lambda: rx.button("x", on_click=rx.noop()), "on_click"),
    "special_call_script": (
        lambda: rx.button("x", on_click=rx.call_script("doThing()")),
        "on_click",
    ),
    "stop_prop_with_arg": (
        lambda: rx.button("x", on_click=_EvState.inc_by(7).stop_propagation),
        "on_click",
    ),
}


@pytest.mark.parametrize("name", list(_CASES))
def test_assembled_event_render_matches_python(name: str) -> None:
    factory, trigger = _CASES[name]
    component = factory()
    expected = _expected(component, trigger)
    got = _assemble_event_chain(component.event_triggers[trigger])
    assert got == expected, (
        f"event[{name}] assembled render differs from Python:\n"
        f"  expected: {expected}\n"
        f"  got:      {got}"
    )


def test_cases_cover_the_grammar() -> None:
    # Guard against the suite silently shrinking.
    assert len(_CASES) >= 18
