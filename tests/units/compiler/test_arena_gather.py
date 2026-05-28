"""Parity tests for the native Python snapshot gatherer (PR C).

``gather_arena(c)`` produces the snapshot wire bundle directly from a
Component tree (no Rust freeze walk). Two contracts are pinned:

1. **Bundle parity** — for the supported subset, ``gather_arena(c)`` equals
   ``dump_snapshot(c)`` modulo the Rust-computed ``subtree_hash`` /
   ``PROPAGATES_HOOKS`` (which ``compile_page_from_arena(...,
   compute_close=True)`` recomputes).
2. **Emit parity** — ``compile_page_from_arena(gather_arena(c),
   compute_close=True)`` is byte-identical to the freeze path
   ``compile_page_from_component_arena(c)``.

Plus the **fallback contract**: features outside the current cut (reactive
state vars, events, control flow) raise :class:`GatherUnsupportedError` rather
than emitting wrong output, so callers can fall back to the freeze path.

This cut covers the structural / leaf surface (Element / Fragment / Bare
with literal props, style, imports). The corpus sweep asserts emit parity
for every fixture the gatherer accepts and tolerates ``GatherUnsupportedError``
for the dynamic ones.
"""

from __future__ import annotations

import pytest

import reflex as rx
from reflex.compiler.arena_record import GatherUnsupportedError, gather_arena
from reflex.compiler.session import CompilerSession

from ._corpus import FIXTURES as _FIXTURES

_PROPAGATES_HOOKS = 1 << 4


class _GatherState(rx.State):
    n: int = 0
    items: list[str] = ["a", "b"]

    def tick(self) -> None:
        self.n += 1


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


def _normalize(bundle: dict) -> dict:
    """Drop the Rust-computed close fields so a gather bundle and a
    dump_snapshot bundle compare equal on the gatherer's own output.

    Args:
        bundle: a wire bundle dict.

    Returns:
        The normalized bundle (no subtree_hash, PROPAGATES_HOOKS masked).
    """
    out = dict(bundle)
    nodes = []
    for n in out["nodes"]:
        n = dict(n)
        n.pop("subtree_hash", None)
        n["flags"] = n.get("flags", 0) & ~_PROPAGATES_HOOKS
        for k in (
            "rendered_props",
            "event_callbacks",
            "imports",
            "hooks_internal",
            "hooks_user",
        ):
            n[k] = [tuple(x) for x in n.get(k, [])]
        n["children"] = tuple(n["children"])
        nodes.append(n)
    out["nodes"] = nodes
    return out


# Components the current cut fully supports.
_SUPPORTED = {
    "box_empty": lambda: rx.box(),
    "text": lambda: rx.text("hi"),
    "fragment": lambda: rx.fragment(rx.text("a")),
    "nested": lambda: rx.box(rx.text("x"), rx.text("y")),
    "box_style": lambda: rx.box(width="10px"),
    "box_multi_style": lambda: rx.box(width="1px", height="2px", padding="3px"),
    "deep": lambda: rx.box(rx.box(rx.text("a"), rx.text("b")), rx.text("c")),
    "vstack": lambda: rx.vstack(rx.text("a"), rx.text("b")),
    "hstack": lambda: rx.hstack(rx.box(), rx.box()),
    "button": lambda: rx.button("Click"),
    "heading": lambda: rx.heading("Title", size="4"),
    "link": lambda: rx.link("go", href="/x"),
    "grid": lambda: rx.grid(rx.text("a")),
}


@pytest.mark.parametrize("name", list(_SUPPORTED))
def test_gather_bundle_matches_dump(sess: CompilerSession, name: str) -> None:
    comp = _SUPPORTED[name]()
    want = _normalize(sess.dump_snapshot(comp))
    got = _normalize(gather_arena(comp))
    assert got == want


@pytest.mark.parametrize("name", list(_SUPPORTED))
def test_gather_emit_matches_freeze(sess: CompilerSession, name: str) -> None:
    comp = _SUPPORTED[name]()
    fp, fb, _ = sess.compile_page_from_component_arena(comp, "Index", "/")
    wp, wb = sess.compile_page_from_arena(
        gather_arena(comp), "Index", "/", compute_close=True
    )
    assert wp == fp
    assert wb == fb


# Features outside the current cut must raise (caller falls back to freeze),
# never silently emit wrong output.
_UNSUPPORTED = {
    "state_prop": lambda: rx.box(width=f"{_GatherState.n}px"),
    "reactive_text": lambda: rx.text(_GatherState.n),
    "event_handler": lambda: rx.button("go", on_click=_GatherState.tick),
    "foreach": lambda: rx.foreach(_GatherState.items, lambda i: rx.text(i)),
    "cond": lambda: rx.cond(_GatherState.n > 0, rx.text("y"), rx.text("n")),
    "match": lambda: rx.match(_GatherState.n, (1, rx.text("one")), rx.text("d")),
}


@pytest.mark.parametrize("name", list(_UNSUPPORTED))
def test_gather_unsupported_raises(name: str) -> None:
    with pytest.raises(GatherUnsupportedError):
        gather_arena(_UNSUPPORTED[name]())


def test_gather_emit_matches_freeze_with_meta(sess: CompilerSession) -> None:
    comp = rx.box(rx.text("hi"))
    kw = {"title": "T", "meta_tags": [("description", "d")]}
    fp, fb, _ = sess.compile_page_from_component_arena(comp, "Index", "/", **kw)
    wp, wb = sess.compile_page_from_arena(
        gather_arena(comp), "Index", "/", compute_close=True, **kw
    )
    assert wp == fp
    assert wb == fb


@pytest.mark.parametrize("fx", _FIXTURES, ids=[f.name for f in _FIXTURES])
def test_corpus_gather_emit_matches_freeze_when_supported(
    sess: CompilerSession, fx
) -> None:
    """For every corpus fixture the gatherer accepts, its emit must match
    the freeze path. Dynamic fixtures (state/events/control flow) are
    expected to raise and fall back — tolerated here.
    """
    comp = fx.build()
    try:
        bundle = gather_arena(comp)
    except GatherUnsupportedError:
        pytest.skip("fixture uses features outside the current gather cut")
    fp, fb, _ = sess.compile_page_from_component_arena(comp, fx.ident, fx.route)
    wp, wb = sess.compile_page_from_arena(
        bundle, fx.ident, fx.route, compute_close=True
    )
    assert wp == fp
    assert wb == fb
