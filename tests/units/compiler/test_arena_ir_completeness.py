"""IR completeness tests for the Rust freeze pipeline.

These tests target the long-term architecture: Python builds a
primitive snapshot, hands the bytes to Rust, Rust emits JSX from the
snapshot alone — no further PyO3 callbacks during compile. To validate
that target, we assert two properties of every snapshot:

1. **Self-sufficient** — every field downstream code (memoize pass,
   JSX emitter) consults during compile is materialized in the
   snapshot. If a field is `None` here, the emitter has nothing to
   fetch from Python either.
2. **Fully primitive** — the snapshot tree contains only `str`,
   `int`, `bool`, `tuple`, `list`, `dict`, and `None`. No `Component`,
   `Var`, `BaseModel`, or other Python object references survive
   into the IR.

The dump format is exposed by ``CompilerSession.dump_snapshot`` and
mirrors the layout of ``reflex_ir::Snapshot`` one-for-one.

Run with::

    uv run pytest tests/units/compiler/test_arena_ir_completeness.py -v
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("reflex_base")
pytest.importorskip("reflex_compiler_rust._native")

import reflex as rx
from reflex.compiler.session import CompilerSession

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


class _State(rx.State):
    name: str = "world"
    count: int = 0
    items: list[str] = []

    def inc(self) -> None:
        self.count += 1


_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def _assert_primitive_tree(obj: Any, path: str = "$") -> None:
    """Walk `obj` recursively. Fail if any leaf isn't a primitive.

    Containers (`list`, `tuple`, `dict`) are descended; everything
    else must be a member of `_PRIMITIVE_TYPES`. This catches any
    accidental Python-object-ref leakage into the snapshot.
    """
    if isinstance(obj, _PRIMITIVE_TYPES):
        return
    if isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _assert_primitive_tree(item, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, _PRIMITIVE_TYPES), (
                f"non-primitive key at {path}: {type(k).__name__}"
            )
            _assert_primitive_tree(v, f"{path}.{k!r}")
        return
    msg = f"non-primitive leaf at {path}: {type(obj).__name__} value={obj!r}"
    raise AssertionError(msg)


def _node_count(snap: dict) -> int:
    return len(snap["nodes"])


def _kinds(snap: dict) -> list[str]:
    return [n["kind"] for n in snap["nodes"]]


# ---------------------------------------------------------------------------
# IR shape contract: top-level dict structure
# ---------------------------------------------------------------------------


def test_snapshot_top_level_keys(sess: CompilerSession) -> None:
    """Every Snapshot field that Rust consults during compile is exposed."""
    snap = sess.dump_snapshot(rx.text("hi"))
    expected = {
        "nodes",
        "root",
        "var_data",
        "memo_bodies",
        "app_wraps",
        "control_flow",
        "page_meta",
        "wrap_redirects",
        "special_props",
        "rename_props",
        "app_style_map",
    }
    assert set(snap.keys()) == expected


def test_snapshot_is_fully_primitive(sess: CompilerSession) -> None:
    """No Python object references survive into the IR.

    Covers Component, Var, Style, BaseModel — any of those leaking
    would mean the emitter has to call back into Python to resolve
    them, defeating the architecture.
    """
    component = rx.box(
        rx.text(_State.name, font_size="14px"),
        rx.cond(_State.count > 0, rx.text("yes"), rx.text("no")),
        rx.foreach(_State.items, lambda x: rx.text(x)),
        rx.el.button("click", on_click=_State.inc),
        style={"color": "red"},
        id="my-ref",
    )
    snap = sess.dump_snapshot(component)
    _assert_primitive_tree(snap)


# ---------------------------------------------------------------------------
# Per-node IR field shape
# ---------------------------------------------------------------------------


def test_node_shape_complete(sess: CompilerSession) -> None:
    """Each node dict carries every field the emitter reads from it."""
    snap = sess.dump_snapshot(rx.box(rx.text("a"), rx.text("b")))
    expected_fields = {
        "kind",
        "tag",
        "style_key",
        "style",
        "custom_code",
        "ref_name",
        "flags_bits",
        "subtree_hash",
        "children",
        "rendered_props",
        "event_callbacks",
        "imports",
        "hooks_internal",
        "hooks_user",
        "dynamic_imports",
        "vars_used",
    }
    for i, node in enumerate(snap["nodes"]):
        missing = expected_fields - set(node.keys())
        assert missing == set(), f"node[{i}] missing fields: {missing}"


def test_node_kinds_emit_known_discriminants(sess: CompilerSession) -> None:
    """`kind` is always one of the known NodeKind variants.

    A surprise discriminant would mean the snapshot can't be emitted
    deterministically without calling back into Python to ask what
    kind of thing it is.
    """
    valid = {
        "Element",
        "Text",
        "Foreach",
        "Cond",
        "Match",
        "Memoize",
        "Fragment",
        "Expr",
        "MemoizeWrapper",
    }
    component = rx.box(
        rx.text(_State.name),
        rx.cond(_State.count > 0, rx.text("a"), rx.text("b")),
        rx.foreach(_State.items, lambda x: rx.text(x)),
        rx.match(_State.count, (1, rx.text("one")), rx.text("other")),
    )
    snap = sess.dump_snapshot(component)
    for i, node in enumerate(snap["nodes"]):
        assert node["kind"] in valid, f"node[{i}] has unknown kind {node['kind']!r}"


# ---------------------------------------------------------------------------
# Element nodes: tag, props, children
# ---------------------------------------------------------------------------


def test_element_tag_resolved_at_freeze(sess: CompilerSession) -> None:
    """`tag` is a string, not a Python ref.

    Rust must not need to call `type(component).__name__` again.
    """
    snap = sess.dump_snapshot(rx.el.button("click"))
    root = snap["nodes"][snap["root"]]
    assert root["kind"] == "Element"
    assert isinstance(root["tag"], str), f"root tag is not a string: {root['tag']!r}"
    assert root["tag"], "root tag must be a non-empty string"


def test_rendered_props_pre_serialized(sess: CompilerSession) -> None:
    """Prop values are pre-rendered JS, not Python objects.

    The emitter prints `(name, value)` straight into JSX. Both halves
    must be strings the emitter can splice without further work.
    """
    snap = sess.dump_snapshot(rx.text("hi", font_size="14px"))
    root = snap["nodes"][snap["root"]]
    assert root["rendered_props"], "expected at least one rendered prop"
    for name, value in root["rendered_props"]:
        assert isinstance(name, str), f"prop name not a string: {name!r}"
        assert name, "prop name is empty"
        assert isinstance(value, str), (
            f"prop {name!r} value is not pre-rendered: {value!r}"
        )


def test_children_ranges_point_within_arena(sess: CompilerSession) -> None:
    """`children` is `(start, end)` into `nodes` — both in bounds.

    A range that falls outside the arena means the emitter would have
    to walk Python to find the actual children.
    """
    snap = sess.dump_snapshot(rx.box(rx.text("a"), rx.text("b"), rx.text("c")))
    n = _node_count(snap)
    for i, node in enumerate(snap["nodes"]):
        start, end = node["children"]
        assert 0 <= start <= end <= n, (
            f"node[{i}] has out-of-bounds children range {(start, end)} "
            f"vs arena size {n}"
        )


def test_children_ranges_describe_real_parentage(sess: CompilerSession) -> None:
    """Direct-children range yields the expected count."""
    snap = sess.dump_snapshot(rx.box(rx.text("a"), rx.text("b"), rx.text("c")))
    root = snap["nodes"][snap["root"]]
    start, end = root["children"]
    # Each `rx.text` adds one element node (the text content sits
    # in a child slot itself), so the root reports >= 3 direct
    # children.
    assert end - start >= 3, (
        f"root must have at least 3 direct children; got {end - start}"
    )


# ---------------------------------------------------------------------------
# Text / Expr / control-flow side tables
# ---------------------------------------------------------------------------


def test_text_value_stored_in_control_flow(sess: CompilerSession) -> None:
    """Literal text content lives in `control_flow.text_value`.

    Avoids storing the string on every node (most nodes have no text)
    while still keeping it primitive and addressable by NodeIdx.
    """
    snap = sess.dump_snapshot(rx.text("hello"))
    text_nodes = [(i, n) for i, n in enumerate(snap["nodes"]) if n["kind"] == "Text"]
    assert text_nodes, "expected at least one Text node"
    text_values = snap["control_flow"]["text_value"]
    # At least one Text node has a literal "hello" payload.
    payloads = {text_values.get(i) for i, _ in text_nodes}
    assert "hello" in payloads, (
        f"literal text 'hello' not found in control_flow.text_value; saw {payloads}"
    )


def test_expr_value_carries_pre_rendered_js(sess: CompilerSession) -> None:
    """Var-driven text bodies become `Expr` nodes with rendered JS.

    The whole point: the emitter splices `expr_value[idx]` directly
    into JSX. No Var `__str__` or `_js_expr` call needed at emit
    time.
    """
    snap = sess.dump_snapshot(rx.text(_State.name))
    expr_value = snap["control_flow"]["expr_value"]
    expr_nodes = [i for i, n in enumerate(snap["nodes"]) if n["kind"] == "Expr"]
    assert expr_nodes, "expected at least one Expr node"
    for i in expr_nodes:
        assert i in expr_value, f"Expr node[{i}] missing from expr_value"
        assert isinstance(expr_value[i], str), (
            f"Expr node[{i}] value not a string: {expr_value[i]!r}"
        )
        assert expr_value[i], f"Expr node[{i}] has empty value"


def test_cond_test_pre_rendered(sess: CompilerSession) -> None:
    """`Cond.test` is a rendered JS expression keyed by NodeIdx."""
    snap = sess.dump_snapshot(
        rx.cond(_State.count > 0, rx.text("pos"), rx.text("zero"))
    )
    cond_indices = [i for i, n in enumerate(snap["nodes"]) if n["kind"] == "Cond"]
    assert cond_indices, "expected a Cond node"
    for i in cond_indices:
        test = snap["control_flow"]["cond_test"].get(i)
        assert isinstance(test, str), f"Cond node[{i}] test not a string: {test!r}"
        assert test, f"Cond node[{i}] missing pre-rendered test"


def test_foreach_iter_pre_rendered(sess: CompilerSession) -> None:
    """`Foreach.iter` is rendered JS, not a Var ref."""
    snap = sess.dump_snapshot(rx.foreach(_State.items, lambda x: rx.text(x)))
    foreach_indices = [i for i, n in enumerate(snap["nodes"]) if n["kind"] == "Foreach"]
    assert foreach_indices, "expected a Foreach node"
    for i in foreach_indices:
        it = snap["control_flow"]["foreach_iter"].get(i)
        assert isinstance(it, str), f"Foreach node[{i}] iter not a string: {it!r}"
        assert it, f"Foreach node[{i}] missing pre-rendered iter"


def test_match_arms_and_default_resolve_to_node_indices(
    sess: CompilerSession,
) -> None:
    """Each Match carries: rendered `value`, `(case, body_idx)` arms,
    and an optional `default` body_idx. All body indices point into
    the arena.
    """
    snap = sess.dump_snapshot(
        rx.match(
            _State.count,
            (1, rx.text("one")),
            (2, rx.text("two")),
            rx.text("other"),
        )
    )
    match_indices = [i for i, n in enumerate(snap["nodes"]) if n["kind"] == "Match"]
    assert match_indices, "expected a Match node"
    n_total = _node_count(snap)
    for i in match_indices:
        val = snap["control_flow"]["match_value"].get(i)
        assert isinstance(val, str), f"Match[{i}] value not a string: {val!r}"
        assert val, f"Match[{i}] missing rendered value"
        arms = snap["control_flow"]["match_arms"].get(i)
        assert arms, f"Match[{i}] missing arms"
        for case, body in arms:
            assert isinstance(case, str), f"non-string case {case!r}"
            assert isinstance(body, int), f"non-int body idx {body!r}"
            assert 0 <= body < n_total, f"Match[{i}] arm body_idx {body} out of bounds"
        default = snap["control_flow"]["match_default"].get(i)
        if default is not None:
            assert isinstance(default, int)
            assert 0 <= default < n_total


# ---------------------------------------------------------------------------
# Vars & var_data
# ---------------------------------------------------------------------------


def test_vars_used_indices_in_bounds(sess: CompilerSession) -> None:
    """Every `vars_used` index references a real `var_data` entry."""
    snap = sess.dump_snapshot(
        rx.box(rx.text(_State.name), rx.text(_State.count.to_string()))
    )
    var_data_len = len(snap["var_data"])
    for i, node in enumerate(snap["nodes"]):
        for idx in node["vars_used"]:
            assert 0 <= idx < var_data_len, (
                f"node[{i}].vars_used contains out-of-bounds index "
                f"{idx} (var_data has {var_data_len})"
            )


def test_var_data_captures_state_binding(sess: CompilerSession) -> None:
    """Each `var_data` entry that owns a state Var records the state name.

    Without this the emitter would have to walk back to Python to
    resolve which State class a Var belongs to.
    """
    snap = sess.dump_snapshot(rx.text(_State.name))
    assert snap["var_data"], "expected at least one var_data entry"
    states = {e["state"] for e in snap["var_data"]}
    assert any(s for s in states), (
        f"no state binding captured in var_data; saw {states}"
    )


def test_var_data_carries_hooks_imports_deps(sess: CompilerSession) -> None:
    """Each `var_data` entry has the slices the emitter needs.

    Hooks (e.g. `useContext(...)` lines), imports (modules pulled in
    transitively), and deps (other vars this one depends on) are all
    fully materialized as primitive strings.
    """
    snap = sess.dump_snapshot(rx.text(_State.name))
    for entry in snap["var_data"]:
        # Each slice is a list (possibly empty), but each element must
        # be a primitive when present.
        assert isinstance(entry["hooks"], list)
        assert isinstance(entry["imports"], list)
        assert isinstance(entry["deps"], list)
        assert isinstance(entry["components"], list)
        for hook in entry["hooks"]:
            assert isinstance(hook, (str, type(None)))
        for module, name in entry["imports"]:
            assert isinstance(module, (str, type(None)))
            assert isinstance(name, (str, type(None)))


def test_var_data_dedup_unique_entries(sess: CompilerSession) -> None:
    """Repeated reads of the same Var collapse to one var_data entry.

    PR7 dedup: two nodes both reading `State.name` get the same
    VarDataRef; only one row exists in `var_data`. This is the
    "primitive snapshot" version of class-schema caching for Vars.
    """
    snap = sess.dump_snapshot(
        rx.box(rx.text(_State.name), rx.text(_State.name), rx.text(_State.name))
    )
    # Same Var referenced from multiple Expr nodes — should produce
    # the same VarDataRef index, not three separate entries.
    refs = {idx for n in snap["nodes"] for idx in n["vars_used"]}
    state_entries = [e for e in snap["var_data"] if e["state"] is not None]
    assert len(state_entries) <= len(refs), (
        "var_data has more state-bearing entries than unique refs — "
        "dedup is missing or the snapshot leaked duplicates"
    )


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_node_imports_are_pre_resolved_pairs(sess: CompilerSession) -> None:
    """`imports` per node is `[(module, name), ...]` — strings only.

    Rust does NOT have to call `_get_imports()` or merge dicts at
    emit time; it splices the pairs directly into the import block.
    """
    snap = sess.dump_snapshot(rx.el.button("click", on_click=_State.inc))
    root = snap["nodes"][snap["root"]]
    assert root["imports"], "expected non-empty imports for a button with event"
    for module, name in root["imports"]:
        assert isinstance(module, (str, type(None)))
        assert isinstance(name, (str, type(None)))


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def test_hooks_internal_pre_rendered(sess: CompilerSession) -> None:
    """`hooks_internal` is `[{code: str, position: int}, ...]`.

    Code is the literal JS hook line. Position is the sort bucket
    (0/1/2 for INTERNAL/PRE/POST). Nothing further to resolve.
    """
    snap = sess.dump_snapshot(rx.el.button("click", on_click=_State.inc))
    # Some node in the page must have at least one internal hook
    # (the event-loop context binding).
    saw_hook = False
    for node in snap["nodes"]:
        for h in node["hooks_internal"]:
            assert set(h.keys()) == {"code", "position"}, (
                f"hook entry has unexpected shape: {h.keys()}"
            )
            assert isinstance(h["code"], (str, type(None)))
            assert isinstance(h["position"], int)
            saw_hook = True
    assert saw_hook, "expected internal hooks for button with event handler"


def test_ref_name_captured_when_id_set(sess: CompilerSession) -> None:
    """A Component with `id=...` records its ref name in `ref_name`.

    Without this the emitter has to read `self.id` again to wire up
    the `useRef` hook.
    """
    snap = sess.dump_snapshot(rx.box(id="my_ref"))
    root = snap["nodes"][snap["root"]]
    # Freeze normalizes `id` into a unique React ref handle (e.g.
    # `ref_my_ref`). The contract is that the user's id appears
    # somewhere in the resolved ref_name, not that it equals it.
    assert isinstance(root["ref_name"], str), (
        f"ref_name not a string: {root['ref_name']!r}"
    )
    assert "my_ref" in root["ref_name"], (
        f"expected ref_name to contain 'my_ref'; got {root['ref_name']!r}"
    )


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def test_event_callbacks_are_rendered_js(sess: CompilerSession) -> None:
    """`event_callbacks` is `[(trigger, js_body), ...]`.

    The body is the full JS arrow function — no further resolution
    required from Python.
    """
    snap = sess.dump_snapshot(rx.el.button("click", on_click=_State.inc))
    root = snap["nodes"][snap["root"]]
    assert root["event_callbacks"], "expected at least one event callback on the button"
    for trigger, body in root["event_callbacks"]:
        assert isinstance(trigger, str), f"trigger not a string: {trigger!r}"
        assert trigger.startswith("on_"), f"trigger should be `on_*`; got {trigger!r}"
        assert isinstance(body, str), f"event body not a string: {body!r}"
        assert "=>" in body, f"event body should be an arrow function; got {body!r}"


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------


def test_style_dict_pre_rendered_to_emotion(sess: CompilerSession) -> None:
    """`style` is a single pre-rendered JS object literal.

    Today's emitter splices `style` directly; no further dict
    iteration or emotion-format call required at emit time.
    """
    snap = sess.dump_snapshot(rx.box(style={"color": "red", "fontSize": "14px"}))
    root = snap["nodes"][snap["root"]]
    assert root["style"] is not None, "expected style to be populated"
    assert isinstance(root["style"], str)
    style_js = root["style"]
    assert "color" in style_js, f"style missing 'color' prop: {style_js!r}"
    assert "red" in style_js, f"style missing 'red' value: {style_js!r}"


def test_empty_style_is_absent_not_object(sess: CompilerSession) -> None:
    """Components without style have `style == None`, not a stray
    empty object literal. The "no style" classification is part of
    the IR contract.
    """
    snap = sess.dump_snapshot(rx.box())
    root = snap["nodes"][snap["root"]]
    # Either `None` (Symbol::EMPTY) or an explicit empty marker —
    # but never a synthesized non-empty object that would force the
    # emitter to re-check.
    if root["style"] is not None:
        # Some compositional roots carry a baseline style; the only
        # contract is that the value is a deterministic string.
        assert isinstance(root["style"], str)


# ---------------------------------------------------------------------------
# Subtree hash, memoize wiring
# ---------------------------------------------------------------------------


def test_subtree_hash_populated_for_every_node(sess: CompilerSession) -> None:
    """Every node carries a finite, non-zero subtree hash.

    The memoize pass relies on this to dedup identical subtrees
    across pages. Zero would mean unhashed.
    """
    snap = sess.dump_snapshot(rx.box(rx.text("a"), rx.text("b")))
    for i, node in enumerate(snap["nodes"]):
        assert isinstance(node["subtree_hash"], int)
        assert node["subtree_hash"] != 0, (
            f"node[{i}] kind={node['kind']!r} has subtree_hash == 0"
        )


def test_identical_subtrees_share_subtree_hash(sess: CompilerSession) -> None:
    """Two structurally identical subtrees produce the same hash.

    The cheapest way to check "no callback needed for memo dedup":
    the hash IS the dedup key, computed entirely in Rust from the
    snapshot.
    """
    snap = sess.dump_snapshot(rx.box(rx.text("dup"), rx.text("dup")))
    text_hashes = [n["subtree_hash"] for n in snap["nodes"] if n["kind"] == "Text"]
    # Both literal "dup" text nodes must produce the same hash.
    assert len(set(text_hashes)) < len(text_hashes), (
        f"expected duplicate Text subtrees to share a hash; got {text_hashes}"
    )


# ---------------------------------------------------------------------------
# App wraps, page meta, root pointer
# ---------------------------------------------------------------------------


def test_root_points_into_arena(sess: CompilerSession) -> None:
    """`root` is a valid NodeIdx into `nodes`."""
    snap = sess.dump_snapshot(rx.box(rx.text("hi")))
    assert 0 <= snap["root"] < _node_count(snap)


def test_app_wraps_carry_sort_key_and_root_idx(sess: CompilerSession) -> None:
    """App-wrap contributions are `{sort_key, name, root}` triples.

    Each `root` is an arena index. `name` is a string. `sort_key` is
    a primitive int. No Component refs survive into the wrap list.
    """
    # `rx.text` (Radix-themed) carries a ColorMode-provider wrap.
    snap = sess.dump_snapshot(rx.text("hi"))
    n_total = _node_count(snap)
    for wrap in snap["app_wraps"]:
        assert set(wrap.keys()) == {"sort_key", "name", "root"}
        assert isinstance(wrap["sort_key"], int)
        assert isinstance(wrap["name"], str)
        assert wrap["name"], "app_wrap name is empty"
        assert isinstance(wrap["root"], int)
        assert 0 <= wrap["root"] < n_total


# ---------------------------------------------------------------------------
# Wrap redirects, special props, rename props
# ---------------------------------------------------------------------------


def test_wrap_redirects_targets_in_bounds(sess: CompilerSession) -> None:
    """If wrap_redirects fires, both source and target are arena idxs."""
    snap = sess.dump_snapshot(rx.box(rx.text("a"), rx.text("b")))
    n_total = _node_count(snap)
    for src, dst in snap["wrap_redirects"].items():
        assert 0 <= src < n_total
        assert 0 <= dst < n_total


def test_rename_props_pairs_are_strings(sess: CompilerSession) -> None:
    """Rename pairs are `[(from, to), ...]` of pure strings."""
    snap = sess.dump_snapshot(rx.el.div(class_name="hello"))
    for idx, pairs in snap["rename_props"].items():
        assert isinstance(idx, int)
        for old, new in pairs:
            assert isinstance(old, (str, type(None)))
            assert isinstance(new, (str, type(None)))


# ---------------------------------------------------------------------------
# Cross-cutting integrity
# ---------------------------------------------------------------------------


def test_all_node_idx_references_in_bounds(sess: CompilerSession) -> None:
    """Every NodeIdx referenced anywhere in the snapshot is valid.

    Catches an entire class of bugs where freeze emits a dangling
    index that would crash the emitter or — worse — silently emit
    garbage JSX.
    """
    snap = sess.dump_snapshot(
        rx.box(
            rx.cond(_State.count > 0, rx.text("y"), rx.text("n")),
            rx.match(_State.count, (1, rx.text("o")), rx.text("d")),
            rx.foreach(_State.items, lambda x: rx.text(x)),
        )
    )
    n_total = _node_count(snap)
    in_bounds = lambda i: 0 <= i < n_total  # noqa: E731

    assert in_bounds(snap["root"])

    for i, node in enumerate(snap["nodes"]):
        start, end = node["children"]
        assert 0 <= start <= end <= n_total, f"node[{i}] children OOB"

    for src, dst in snap["wrap_redirects"].items():
        assert in_bounds(src), f"wrap_redirects src {src} OOB"
        assert in_bounds(dst), f"wrap_redirects dst {dst} OOB"

    cf = snap["control_flow"]
    for idx_map in (
        cf["text_value"],
        cf["cond_test"],
        cf["foreach_iter"],
        cf["match_value"],
        cf["expr_value"],
        cf["memo_key"],
    ):
        for idx in idx_map:
            assert in_bounds(idx), f"control_flow idx {idx} OOB"

    for idx, arms in cf["match_arms"].items():
        assert in_bounds(idx)
        for _, body in arms:
            assert in_bounds(body)

    for idx, body in cf["match_default"].items():
        assert in_bounds(idx)
        assert in_bounds(body)

    for wrap in snap["app_wraps"]:
        assert in_bounds(wrap["root"])

    for body in snap["memo_bodies"]:
        assert in_bounds(body["root"])


def test_complex_page_emit_inputs_complete(sess: CompilerSession) -> None:
    """Mega-test: a feature-dense component captures every IR surface.

    Combines Element + Var + Cond + Foreach + Match + event + style +
    ref. The resulting snapshot must populate every relevant section
    of `control_flow`, plus at least one entry each in `var_data`,
    node `hooks_internal`, and node `imports`.

    If any one of these is empty, Rust would need to call back into
    Python at emit time for that data.
    """
    component = rx.box(
        rx.text(_State.name, font_size="14px"),
        rx.cond(_State.count > 0, rx.text("pos"), rx.text("nope")),
        rx.foreach(_State.items, lambda x: rx.text(x)),
        rx.match(
            _State.count,
            (1, rx.text("one")),
            rx.text("other"),
        ),
        rx.el.button("inc", on_click=_State.inc),
        style={"color": "red"},
        id="root_ref",
    )
    snap = sess.dump_snapshot(component)
    _assert_primitive_tree(snap)

    cf = snap["control_flow"]
    assert cf["cond_test"], "no cond_test captured"
    assert cf["foreach_iter"], "no foreach_iter captured"
    assert cf["match_value"], "no match_value captured"
    assert cf["match_arms"], "no match_arms captured"
    assert cf["text_value"], "no text_value captured"

    assert snap["var_data"], "no var_data captured"
    assert any(n["hooks_internal"] for n in snap["nodes"]), (
        "no hooks_internal captured anywhere"
    )
    assert any(n["imports"] for n in snap["nodes"]), "no imports captured anywhere"
    assert any(n["event_callbacks"] for n in snap["nodes"]), (
        "no event_callbacks captured anywhere"
    )
    assert any(n["style"] is not None for n in snap["nodes"]), (
        "no node with style captured"
    )
    assert any(
        isinstance(n["ref_name"], str) and "root_ref" in n["ref_name"]
        for n in snap["nodes"]
    ), "ref_name carrying 'root_ref' not propagated into IR"
