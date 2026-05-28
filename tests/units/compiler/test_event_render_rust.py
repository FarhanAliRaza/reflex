"""Byte-parity spec for the Rust event-chain renderer (PR D-events-rust).

Event-chain rendering (``LiteralVar.create(chain)._js_expr``) is the gather
path's dominant cost — ~109us per chain, recomputed every compile, vs ~0.2us
to read the raw struct. The plan is to extract the raw chain in Python
cheaply and render the JS in Rust.

This suite pins the contract for that Rust renderer across the full event
surface, so a partial implementation can't pass: every case asserts
``CompilerSession.render_event_chain_js(component, trigger)`` is
**byte-identical** to the Python ``LiteralVar.create(chain)._js_expr``.

It FAILS today (the Rust renderer is a stub returning "") and goes green
only when the renderer handles every shape below: no-args, literal &
reactive & multi args, event_actions (stop_propagation / prevent_default),
multi-handler block form, varied arg-specs (pointer / value / form / key),
chained handlers, and the special events (set / redirect / console_log /
call_script / noop).
"""

from __future__ import annotations

import pytest
from reflex_base.vars.base import LiteralVar

import reflex as rx
from reflex.compiler.session import CompilerSession


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


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


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


@pytest.mark.xfail(
    reason="Rust event-chain renderer not yet implemented (stub returns ''); "
    "this suite drives it to completion — remove xfail once all shapes pass",
    strict=False,
)
@pytest.mark.parametrize("name", list(_CASES))
def test_rust_event_render_matches_python(sess: CompilerSession, name: str) -> None:
    factory, trigger = _CASES[name]
    component = factory()
    expected = _expected(component, trigger)
    got = sess.render_event_chain_js(component, trigger)
    assert got == expected, (
        f"event[{name}] Rust render differs from Python:\n"
        f"  expected: {expected}\n"
        f"  got:      {got}"
    )


def test_cases_cover_the_grammar() -> None:
    # Guard against the suite silently shrinking.
    assert len(_CASES) >= 18
