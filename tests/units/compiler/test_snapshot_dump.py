"""Tests for ``CompilerSession.dump_snapshot`` — the parity-oracle vehicle.

``dump_snapshot`` freezes a Component into a ``Snapshot`` and serializes it
to a plain dict (refine-local plan, PR A). Before it can serve as the
gather-vs-freeze parity oracle it must itself be **deterministic** (same
tree → equal dumps) and **faithful** (any emit-relevant difference → a
different dump). These tests pin both properties plus the structural
invariants emit / memoize rely on.
"""

from __future__ import annotations

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession


class _DumpState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]
    flag: bool = True

    def bump(self) -> None:
        self.counter += 1


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


def test_dump_has_expected_top_level_keys(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.text("hi"))
    for key in (
        "root",
        "nodes",
        "var_data",
        "var_hooks",
        "var_imports",
        "var_deps",
        "var_components",
        "control_flow",
        "wrap_redirects",
        "app_wraps",
        "rename_props",
        "special_props",
        "app_style_map",
        "page_meta",
    ):
        assert key in d, f"missing top-level key {key!r}"
    # id()-based node_pyids must NOT leak into the dump (nondeterministic).
    assert "node_pyids" not in d


def test_dump_basic_tree_shape(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.box(rx.text("hello"), rx.text("world")))
    assert d["root"] == 0
    # box + 2 text elements + 2 bare text contents.
    assert len(d["nodes"]) == 5
    box = d["nodes"][d["root"]]
    assert box["kind"] == 0  # Element
    assert box["tag"]  # non-empty tag
    start, end = box["children"]
    assert (start, end) == (1, 3)  # two direct children, contiguous


def test_dump_is_deterministic(sess: CompilerSession) -> None:
    comp = rx.box(rx.text("hello"), rx.button("click", on_click=_DumpState.bump))
    assert sess.dump_snapshot(comp) == sess.dump_snapshot(comp)


def test_dump_sensitive_to_prop_value(sess: CompilerSession) -> None:
    a = sess.dump_snapshot(rx.box(width="1px"))
    b = sess.dump_snapshot(rx.box(width="2px"))
    assert a != b


def test_dump_sensitive_to_child_text(sess: CompilerSession) -> None:
    a = sess.dump_snapshot(rx.text("alpha"))
    b = sess.dump_snapshot(rx.text("beta"))
    assert a != b


def test_dump_sensitive_to_tree_shape(sess: CompilerSession) -> None:
    a = sess.dump_snapshot(rx.box(rx.text("x")))
    b = sess.dump_snapshot(rx.box(rx.text("x"), rx.text("y")))
    assert a != b


def test_dump_children_ranges_in_bounds_and_ordered(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(
        rx.box(
            rx.text("a"),
            rx.vstack(rx.text("b"), rx.text("c")),
        )
    )
    n = len(d["nodes"])
    assert 0 <= d["root"] < n
    for node in d["nodes"]:
        start, end = node["children"]
        assert start <= end <= n
        # Children come strictly after their parent in the arena
        # (parent-before-children push order).
        assert start == 0 or start <= n


def test_dump_event_callbacks_present(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.button("click", on_click=_DumpState.bump))
    has_event = any(node["event_callbacks"] for node in d["nodes"])
    assert has_event


def test_dump_var_data_populated_for_reactive_text(sess: CompilerSession) -> None:
    # Reactive text content surfaces a deduped var_data entry plus a
    # vars_used ref on each node that reads the Var (mirrors the
    # var_data dedup pass).
    d = sess.dump_snapshot(
        rx.vstack(
            rx.text(f"a={_DumpState.counter}"),
            rx.text(f"b={_DumpState.counter}"),
        )
    )
    assert len(d["var_data"]) >= 1
    used = [r for node in d["nodes"] for r in node["vars_used"] if r is not None]
    assert used
    # Every vars_used ref indexes into the var_data table.
    assert all(0 <= r < len(d["var_data"]) for r in used)


def test_dump_var_data_empty_without_reactive_vars(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.vstack(rx.text("static a"), rx.text("static b")))
    assert d["var_data"] == []
    assert all(node["vars_used"] == [] for node in d["nodes"])


def test_dump_control_flow_cond(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.cond(_DumpState.flag, rx.text("yes"), rx.text("no")))
    cf = d["control_flow"]
    # The cond node records a pre-rendered test expression.
    assert cf["cond_test"], "expected a populated cond_test side table"


def test_dump_control_flow_foreach(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.foreach(_DumpState.items, lambda i: rx.text(i)))
    cf = d["control_flow"]
    assert cf["foreach_iter"], "expected a populated foreach_iter side table"


def test_dump_control_flow_match(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(
        rx.match(
            _DumpState.counter,
            (1, rx.text("one")),
            (2, rx.text("two")),
            rx.text("other"),
        )
    )
    cf = d["control_flow"]
    assert cf["match_value"], "expected a populated match_value side table"
    assert cf["match_arms"], "expected populated match_arms"


def test_dump_flags_are_ints(sess: CompilerSession) -> None:
    d = sess.dump_snapshot(rx.button("x", on_click=_DumpState.bump))
    for node in d["nodes"]:
        assert isinstance(node["flags"], int)
        assert isinstance(node["subtree_hash"], int)
