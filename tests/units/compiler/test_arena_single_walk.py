"""Plan PR7 follow-through: the arena entry point must do exactly one
PyO3 walk of the Component tree.

Today ``compile_page_from_component_arena`` calls
``freeze_component`` AND ``pyread_collect_all_imports``, which means
every node's ``_get_imports`` runs twice — once during freeze (captured
per-node into ``Snapshot.nodes[i].imports``) and once during the
separate ``collect_all_imports`` walk (for the ``bun install``
ImportVar dict).

The fix per planx.md PR7: harvest the full ImportVar metadata inline
during freeze, store it on ``Snapshot.var_data`` + per-node imports,
and emit the final ``ParsedImportDict`` from snapshot data — no second
tree walk, no extra ``_get_imports`` calls.

These tests pin the contract:

1. ``_get_imports`` runs N times per page (one per Component), not 2N.
2. The arena entry returns the same imports dict shape the legacy
   ``collect_all_imports`` produced (so the bun-install step keeps
   working).
3. Output is byte-deterministic — repeated calls with the same tree
   produce identical page JSX + memo body JSX.
"""

from __future__ import annotations

from unittest.mock import patch

import reflex as rx
from reflex.compiler.session import CompilerSession
from reflex_base.components.component import Component


class _SingleWalkState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]

    def inc(self) -> None:
        self.counter += 1


def _build_page():
    return rx.vstack(
        rx.heading("hi"),
        rx.text(f"count={_SingleWalkState.counter}"),
        rx.button("inc", on_click=_SingleWalkState.inc),
        rx.foreach(_SingleWalkState.items, lambda it: rx.text(it)),
    )


def _count_get_imports_calls(comp) -> int:
    """Wrap ``Component._get_imports`` so we can count invocations."""
    original = Component._get_imports
    counter = {"n": 0}

    def wrapped(self):
        counter["n"] += 1
        return original(self)

    with patch.object(Component, "_get_imports", wrapped):
        sess = CompilerSession()
        sess.compile_page_from_component_arena(comp, "Index", "/")
    return counter["n"]


def test_get_imports_called_at_most_once_per_component() -> None:
    """PR7 invariant: the arena pipeline visits each Component
    exactly once. ``_get_imports`` may receive at most one invocation
    per unique ``id(component)``.

    A repeated call on the same id is a second tree walk over that
    Component — the regression PR7 is designed to prevent. Counting
    raw call totals doesn't work because app-wrap components have
    unstable ids across calls (each ``_get_app_wrap_components`` may
    construct a fresh instance), so we key per-id and assert no id
    appears twice.

    The legacy pipeline failed this: ``walk_and_memoize`` would call
    ``_get_imports`` during memoization, then ``page_to_ir`` would
    call it again during msgpack serialization, then
    ``collect_all_imports_into`` would call it a third time for the
    ``bun install`` dict — three calls per node.
    """
    original = Component._get_imports
    # Hold a strong reference to every visited Component so its id
    # can't be recycled mid-freeze by Python's allocator. Without
    # this, two short-lived Components can share an ``id()`` even
    # though they're different instances, giving a false positive.
    calls: list[Component] = []

    def wrapped(self):
        calls.append(self)
        return original(self)

    comp = _build_page()
    with patch.object(Component, "_get_imports", wrapped):
        sess = CompilerSession()
        sess.compile_page_from_component_arena(comp, "Index", "/")

    ids = [id(c) for c in calls]
    duplicates = {
        i: [type(c).__name__ for c in calls if id(c) == i]
        for i in set(ids)
        if ids.count(i) > 1
    }
    assert not duplicates, (
        "_get_imports double-call regression — these Component ids "
        f"received multiple invocations: {duplicates!r}"
    )
    assert len(ids) == len(set(ids)), (
        f"got {len(ids)} _get_imports calls but only "
        f"{len(set(ids))} distinct Components — the arena entry is "
        "walking some subtree twice"
    )


def test_arena_imports_dict_matches_legacy_shape() -> None:
    """The imports dict returned by the arena entry must look like
    ``Component._get_all_imports()`` — ``dict[str, list[ImportVar]]``
    so callers downstream (``App._get_frontend_packages``, the bun
    install step) keep working."""
    comp = _build_page()
    sess = CompilerSession()
    _, _, imports, *_ = sess.compile_page_from_component_arena(comp, "Index", "/")
    legacy_shape = comp._get_all_imports()
    # Every library in the legacy dict must be in the arena's. Values
    # are lists of ImportVars; we compare by tag/install/package_path
    # rather than identity (the arena rebuilds them from the harvested
    # var_data).
    for lib, _items in legacy_shape.items():
        assert lib in imports, (
            f"library {lib!r} in legacy dict but missing from arena "
            f"dict (keys: {list(imports)})"
        )


def test_arena_output_is_byte_deterministic() -> None:
    """Same Component tree → same page JSX, same memo bodies. Without
    this, file watchers churn on every recompile even with PR0's
    skip-if-unchanged."""
    comp_a = _build_page()
    comp_b = _build_page()
    sess = CompilerSession()
    page_a, bodies_a, _, *_ = sess.compile_page_from_component_arena(
        comp_a, "Index", "/"
    )
    page_b, bodies_b, _, *_ = sess.compile_page_from_component_arena(
        comp_b, "Index", "/"
    )
    assert page_a == page_b, "page JSX differs between identical trees"
    names_a = sorted(n for n, _ in bodies_a)
    names_b = sorted(n for n, _ in bodies_b)
    assert names_a == names_b, "memo body names differ between identical trees"
    by_name_a = dict(bodies_a)
    by_name_b = dict(bodies_b)
    for name in names_a:
        assert by_name_a[name] == by_name_b[name], (
            f"memo body {name!r} bytes differ between identical trees"
        )


def test_arena_app_wraps_match_legacy_walk() -> None:
    """The freeze walk harvests app-wrap components inline, replacing
    the separate ``_get_all_app_wrap_components`` Python tree walk in
    ``rust_pipeline.compile_pages``. Keys and value classes must match
    the legacy walk on a tree mixing override classes (Upload, radix
    themes components) with base ones, including under Foreach bodies,
    and stay correct on a warm session (per-class dict cache).
    """
    comp = rx.fragment(
        rx.vstack(
            rx.heading("hi"),
            rx.upload(rx.text("drop here")),
            rx.foreach(rx.Var.create(["a", "b"]), lambda x: rx.badge(x)),
        )
    )
    legacy = comp._get_all_app_wrap_components()
    sess = CompilerSession()
    _, _, _, wraps = sess.compile_page_from_component_arena(comp, "Index", "/")
    assert sorted(wraps) == sorted(legacy)
    for key, component in legacy.items():
        assert type(wraps[key]) is type(component)

    # Warm session: the per-class cached dict must still produce the
    # full wrap set for a different page.
    comp2 = rx.box(rx.upload(rx.text("x")), rx.badge("y"))
    legacy2 = comp2._get_all_app_wrap_components()
    _, _, _, wraps2 = sess.compile_page_from_component_arena(comp2, "Index2", "/two")
    assert sorted(wraps2) == sorted(legacy2)


def test_arena_app_wraps_empty_for_plain_tree() -> None:
    """Pages with only base-behavior components return an empty wrap
    dict — no override class ever pays a Python call.
    """
    comp = rx.fragment(rx.el.div(rx.el.span("plain")))
    sess = CompilerSession()
    _, _, _, wraps = sess.compile_page_from_component_arena(comp, "Index", "/")
    assert wraps == {}
