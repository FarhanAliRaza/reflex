"""Parity gate: the wire path emits byte-identically to the freeze path.

``compile_page_from_arena(dump_snapshot(c))`` rebuilds the ``Snapshot``
from the wire dict (the inverse of ``dump_snapshot``) and runs the same
memoize + emit tail as ``compile_page_from_component_arena(c)``. For any
component the two must produce byte-identical page JSX and memo bodies —
that is the contract the future Python gatherer is validated against
(refine-local plan, PR A parity gate).

Coverage:

* The whole ``tests/codegen_corpus`` (text, box, nesting, styled, cond,
  foreach, match, state vars, computed vars, events, custom attrs, style
  dicts, nested control flow, keys, …) — gate #1.
* Hand-built cases for the title / meta / custom-code / hooks parameters
  and for multi-memo-body pages.
"""

from __future__ import annotations

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession

from ._corpus import FIXTURES as _FIXTURES


class _WireState(rx.State):
    count: int = 0
    label: str = "hi"

    def tick(self) -> None:
        self.count += 1


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


def _freeze(sess: CompilerSession, comp, ident="Index", route="/", **kw):
    page, bodies, _imports = sess.compile_page_from_component_arena(
        comp, ident, route, **kw
    )
    return page, bodies


def _wire(sess: CompilerSession, comp, ident="Index", route="/", **kw):
    bundle = sess.dump_snapshot(comp)
    return sess.compile_page_from_arena(bundle, ident, route, **kw)


@pytest.mark.parametrize("fx", _FIXTURES, ids=[f.name for f in _FIXTURES])
def test_corpus_wire_matches_freeze(sess: CompilerSession, fx) -> None:
    comp = fx.build()
    fp, fb = _freeze(sess, comp, fx.ident, fx.route)
    wp, wb = _wire(sess, comp, fx.ident, fx.route)
    assert wp == fp, f"corpus[{fx.name}]: page JSX differs"
    assert wb == fb, f"corpus[{fx.name}]: memo bodies differ"


def test_corpus_is_non_empty() -> None:
    # Guard against a silently-empty parametrization (e.g. corpus moved).
    assert len(_FIXTURES) >= 10


def test_wire_matches_freeze_with_meta_and_extras(sess: CompilerSession) -> None:
    comp = rx.box(rx.text("hi"), rx.button("go", on_click=_WireState.tick))
    kw = {
        "title": "My Title",
        "meta_tags": [("description", "a page"), ("og:type", "website")],
        "custom_code": ["const EXTRA = 1;"],
        "hooks_body": "const localHook = 2;",
    }
    fp, fb = _freeze(sess, comp, **kw)
    wp, wb = _wire(sess, comp, **kw)
    assert wp == fp
    assert wb == fb


def test_wire_matches_freeze_multi_memo(sess: CompilerSession) -> None:
    # A tree that produces several memo bodies — exercises memo body
    # dedup + emit through the wire path.
    comp = rx.vstack(
        rx.foreach(_WireState.label, lambda c: rx.text(c)),
        rx.cond(_WireState.count > 0, rx.text("pos"), rx.text("neg")),
        rx.button("go", on_click=_WireState.tick),
    )
    fp, fb = _freeze(sess, comp)
    wp, wb = _wire(sess, comp)
    assert wp == fp
    assert wb == fb
    assert len(fb) >= 1  # at least one memo body emitted


def test_wire_path_is_deterministic(sess: CompilerSession) -> None:
    comp = rx.box(rx.text(f"n={_WireState.count}"))
    assert _wire(sess, comp) == _wire(sess, comp)


def test_wire_matches_freeze_on_nested_state_tree(sess: CompilerSession) -> None:
    comp = rx.box(
        rx.vstack(
            rx.text(f"count={_WireState.count}"),
            rx.hstack(
                rx.text(_WireState.label),
                rx.button("x", on_click=_WireState.tick),
            ),
        ),
        width="100%",
    )
    fp, fb = _freeze(sess, comp)
    wp, wb = _wire(sess, comp)
    assert wp == fp
    assert wb == fb
