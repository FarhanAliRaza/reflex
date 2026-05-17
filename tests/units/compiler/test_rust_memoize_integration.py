"""Phase 2 Part B integration tests for the Rust-side memoize transformation.

Exercises :meth:`CompilerSession.set_memoize_in_rust` end-to-end:

* Flag default is OFF (no memo bodies registered, output identical to
  the un-memoized baseline).
* Flag ON wires memoize candidates through the Rust ``read_page`` walk,
  emitting ``Component::MemoCall`` IR nodes (renders as
  ``jsx(<ExportName>, {}, ...children)``), registering the
  ``$/utils/components/<name>`` import, and stashing the wrapper body
  into the per-page memo-body collector.
* Nested memos produce nested ``MemoCall`` nodes with distinct exports.
* Snapshot-strategy candidates (``MemoizationLeaf`` subclasses) emit a
  ``jsx(<Name>, {})`` call site with no children — the body owns the
  full subtree.
"""

from __future__ import annotations

import pytest
from reflex_base.vars import VarData
from reflex_base.vars.base import LiteralVar

import reflex as rx
from reflex.compiler.session import CompilerSession

pytest.importorskip("reflex_base")
pytest.importorskip("reflex_components_core")
pytest.importorskip("reflex_compiler_rust._native")


# A Var carrying state metadata — same shape as the one used in
# `tests/units/compiler/test_memoize_plugin.py`. Components whose own
# props bind this Var are unconditional memo candidates under the
# legacy ``_should_memoize`` heuristic that the Rust port mirrors.
_STATE_VAR = LiteralVar.create("value")._replace(
    merge_var_data=VarData(hooks={"useTestState": None}, state="TestState")
)


@pytest.fixture(autouse=True)
def _reset_memoize_flag() -> None:
    """Make sure the thread-local flag never leaks into another test."""
    sess = CompilerSession()
    sess.set_memoize_in_rust(False)
    # Drain any leftover bodies from a previous compile so the
    # populated-collector assertions below see only this test's data.
    sess.take_memo_bodies()


def test_memoize_in_rust_default_off_unchanged_output() -> None:
    """With the flag OFF, output matches the un-memoized baseline."""
    sess = CompilerSession()
    page_root = rx.fragment(rx.box(rx.text("hello")))
    js = sess.compile_page_from_component("Bench", page_root, "/")
    bodies = sess.take_memo_bodies()
    assert bodies == {}, "no memo bodies should be collected when flag is off"
    # No `$/utils/components/...` import line should appear in the
    # baseline output for a plain component tree.
    assert "$/utils/components/" not in js


def test_memoize_in_rust_emits_memo_call_jsx() -> None:
    """Flag on, page output contains MemoCall syntax for a state-bound candidate."""
    sess = CompilerSession()
    sess.set_memoize_in_rust(True)
    page_root = rx.fragment(rx.box("static", id=_STATE_VAR))
    js = sess.compile_page_from_component("Bench", page_root, "/")
    bodies = sess.take_memo_bodies()
    assert bodies, "memoize-candidate component should register at least one body"
    name = next(iter(bodies))
    # JSX call site uses the export name as the tag, and the module
    # is imported from `$/utils/components/<name>`.
    assert f"jsx({name}" in js
    assert f"$/utils/components/{name}" in js
    # The (body, signature) tuple shape Phase 2 Part C documents.
    body, signature = bodies[name]
    assert isinstance(signature, str)
    assert body is not None


def test_memoize_in_rust_nested_memos() -> None:
    """Outer + inner candidate both produce MemoCall nodes."""
    sess = CompilerSession()
    sess.set_memoize_in_rust(True)
    # Outer + inner both bind state vars in props → both memoize.
    inner = rx.box("inner", id=_STATE_VAR)
    outer = rx.box(inner, id=_STATE_VAR)
    page_root = rx.fragment(outer)
    js = sess.compile_page_from_component("Bench", page_root, "/")
    bodies = sess.take_memo_bodies()
    # The two candidates may resolve to the same memo wrapper (cppm
    # dedupes identical bodies — see
    # `test_memoize_wrapper_deduped_across_repeated_subtrees`). Allow
    # either 1 or 2 entries, but every collected name must surface in
    # the JSX as a `jsx(<Name>, ...)` call site AND in the imports.
    assert len(bodies) >= 1
    for name in bodies:
        assert f"jsx({name}" in js
        assert f"$/utils/components/{name}" in js


def test_memoize_in_rust_snapshot_memo_has_empty_call_children() -> None:
    """Snapshot strategy ⇒ MemoCall with no children passed at call site."""
    sess = CompilerSession()
    sess.set_memoize_in_rust(True)
    # `rx.upload` subclasses `MemoizationLeaf` (recursive=False), so it
    # qualifies as a snapshot-boundary candidate. Bind a state var
    # inside so `_should_memoize`'s snapshot branch flips True.
    upload = rx.upload(rx.text("drop"), id=_STATE_VAR)
    page_root = rx.fragment(upload)
    js = sess.compile_page_from_component("Bench", page_root, "/")
    bodies = sess.take_memo_bodies()
    assert bodies, "upload + state var should produce a snapshot memo"
    # Find at least one snapshot-signature entry, and check its call
    # site renders without trailing children — i.e. `jsx(<Name>, {})`
    # with the closing paren immediately after.
    snapshot_names = [n for n, (_, sig) in bodies.items() if sig == "()"]
    assert snapshot_names, "expected at least one snapshot ('()') memo body"
    name = snapshot_names[0]
    # Snapshot call site: `jsx(<Name>, {})` with no children args.
    assert f"jsx({name}, {{}})" in js
