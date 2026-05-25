"""Parity oracle: Python ``_should_memoize`` must agree with the Rust
arena predicate ``should_memoize_arena`` on every Component shape the
auto-memoize compiler walks. Plan PR3 verification.

The Rust side runs the predicate via
``CompilerSession.should_memoize_arena_for_component`` — a thin wrapper
that freezes the component, applies ``memoize_arena_pass``'s
``should_memoize_arena`` to the root node, and returns the bool. The
fixtures below exercise every branch of the
``reflex.compiler.plugins.memoize._should_memoize`` decision tree:

* disposition = NEVER short-circuit
* disposition = ALWAYS short-circuit
* Bare with reactive contents Var
* Bare with non-reactive contents Var
* tag-none non-control-flow early skip
* Foreach (structural memo child, non-boundary)
* Snapshot boundary with reactive descendant
* Snapshot boundary without reactive descendant
* Plain element with state-reading prop
* Plain element with event trigger
* Plain element with no state/events
"""

from __future__ import annotations

import pytest

import reflex as rx
from reflex.compiler.plugins.memoize import _should_memoize
from reflex.compiler.session import CompilerSession
from reflex_base.constants.compiler import MemoizationDisposition, MemoizationMode
from reflex_components_core.base.bare import Bare


class _ParityState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]

    def increment(self) -> None:
        self.counter += 1


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


def _parity(sess: CompilerSession, comp) -> tuple[bool, bool]:
    py = _should_memoize(comp)
    rust = sess.should_memoize_arena_for_component(comp)
    return py, rust


def test_parity_plain_element(sess: CompilerSession) -> None:
    comp = rx.text("hello")
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_reactive_prop_var(sess: CompilerSession) -> None:
    comp = rx.box(width=f"{_ParityState.counter}px")
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_event_trigger(sess: CompilerSession) -> None:
    comp = rx.button("click", on_click=_ParityState.increment)
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_bare_with_reactive_contents(sess: CompilerSession) -> None:
    comp = Bare.create(contents=_ParityState.counter)
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_bare_with_static_contents(sess: CompilerSession) -> None:
    comp = Bare.create(contents="static")
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_disposition_never(sess: CompilerSession) -> None:
    comp = rx.button("click", on_click=_ParityState.increment)
    comp._memoization_mode = MemoizationMode(
        disposition=MemoizationDisposition.NEVER
    )
    py, rust = _parity(sess, comp)
    assert py == rust
    assert rust is False


def test_parity_disposition_always(sess: CompilerSession) -> None:
    comp = rx.text("static")
    comp._memoization_mode = MemoizationMode(
        disposition=MemoizationDisposition.ALWAYS
    )
    py, rust = _parity(sess, comp)
    assert py == rust
    assert rust is True


def test_parity_foreach_structural_memo_child(sess: CompilerSession) -> None:
    comp = rx.foreach(_ParityState.items, lambda item: rx.text(item))
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_cond_with_reactive_branch(sess: CompilerSession) -> None:
    comp = rx.cond(_ParityState.counter > 0, rx.text("yes"), rx.text("no"))
    py, rust = _parity(sess, comp)
    assert py == rust


def test_parity_nested_tree(sess: CompilerSession) -> None:
    # Subtree with a stateful descendant — the parent shouldn't memoize
    # unless it's a snapshot boundary; the descendant should.
    descendant = rx.button("click", on_click=_ParityState.increment)
    parent = rx.vstack(rx.text("static"), descendant)
    py_parent, rust_parent = _parity(sess, parent)
    py_desc, rust_desc = _parity(sess, descendant)
    assert py_parent == rust_parent
    assert py_desc == rust_desc
