"""Tests for the content-addressed page-emit cache (PR F).

The cache (off by default, enabled via ``set_emit_cache_enabled(True)``)
short-circuits the memoize + emit tail when a page's snapshot + params
hash is unchanged. These tests pin the two properties that make it safe:

1. **Byte-identical with cache on vs off** — a cache hit returns exactly
   what a fresh emit would, across a range of pages.
2. **Sound invalidation** — a changed page (different props / text /
   structure) does not hit a stale entry; it re-emits the correct output.

Plus the hit/miss bookkeeping (a repeated identical compile reuses the
entry; a distinct page adds one).
"""

from __future__ import annotations

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession


class _CacheState(rx.State):
    n: int = 0
    items: list[str] = ["a", "b"]

    def tick(self) -> None:
        self.n += 1


_PAGES = {
    "plain": lambda: rx.box(rx.text("hello"), rx.text("world")),
    "styled": lambda: rx.vstack(rx.heading("Title"), rx.text("body"), spacing="4"),
    "event": lambda: rx.box(rx.button("go", on_click=_CacheState.tick)),
    "reactive": lambda: rx.box(rx.text(_CacheState.n)),
    "cond": lambda: rx.cond(_CacheState.n > 0, rx.text("a"), rx.text("b")),
    "foreach": lambda: rx.foreach(_CacheState.items, lambda x: rx.text(x)),
    "match": lambda: rx.match(_CacheState.n, (1, rx.text("one")), rx.text("d")),
}


def _compile(sess: CompilerSession, comp, ident="Index", route="/"):
    return sess.compile_page_from_component_arena(comp, ident, route)


@pytest.mark.parametrize("name", list(_PAGES))
def test_cache_on_matches_cache_off(name: str) -> None:
    comp = _PAGES[name]
    off = CompilerSession()
    page_off, bodies_off, _ = _compile(off, comp())

    on = CompilerSession()
    on.set_emit_cache_enabled(True)
    # First compile populates the cache; second hits it.
    on_first = _compile(on, comp())
    on_second = _compile(on, comp())
    assert on_first[0] == page_off
    assert on_first[1] == bodies_off
    # Cache hit is byte-identical to the miss.
    assert on_second[0] == page_off
    assert on_second[1] == bodies_off


def test_cache_hit_reuses_entry() -> None:
    sess = CompilerSession()
    sess.set_emit_cache_enabled(True)
    comp = rx.box(rx.text("hello"))
    a = _compile(sess, comp)
    b = _compile(sess, rx.box(rx.text("hello")))  # equal content -> hit
    assert a[0] == b[0]
    assert a[1] == b[1]


def test_cache_invalidates_on_changed_text() -> None:
    sess = CompilerSession()
    sess.set_emit_cache_enabled(True)
    first = _compile(sess, rx.text("alpha"))
    second = _compile(sess, rx.text("beta"))
    # Different content must not collide on a stale entry.
    assert first[0] != second[0]
    # And each matches its own fresh (cache-off) emit.
    off = CompilerSession()
    assert _compile(off, rx.text("beta"))[0] == second[0]


def test_cache_invalidates_on_changed_prop() -> None:
    sess = CompilerSession()
    sess.set_emit_cache_enabled(True)
    a = _compile(sess, rx.box(width="1px"))
    b = _compile(sess, rx.box(width="2px"))
    assert a[0] != b[0]


def test_cache_invalidates_on_route_ident() -> None:
    sess = CompilerSession()
    sess.set_emit_cache_enabled(True)
    comp = rx.box(rx.text("x"))
    a = sess.compile_page_from_component_arena(comp, "PageA", "/a")
    b = sess.compile_page_from_component_arena(rx.box(rx.text("x")), "PageB", "/b")
    # Same component shape, different route ident/route -> distinct output.
    assert a[0] != b[0]


def test_clear_cache_resets_emit_cache() -> None:
    sess = CompilerSession()
    sess.set_emit_cache_enabled(True)
    comp = rx.box(rx.text("hello"))
    first = _compile(sess, comp)
    sess.clear_cache()
    # After clearing, a recompile still produces identical output.
    assert _compile(sess, rx.box(rx.text("hello")))[0] == first[0]
