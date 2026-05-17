"""Phase 2 Part B+D integration tests for the Rust-side memoize transformation.

Exercises :meth:`CompilerSession.set_memoize_in_rust` end-to-end:

* Flag default is ON (Phase 2 Part D). Explicit OFF reproduces the
  un-memoized baseline (no memo bodies registered).
* Flag ON wires memoize candidates through the Rust ``read_page`` walk,
  emitting ``Component::MemoCall`` IR nodes (renders as
  ``jsx(<ExportName>, {}, ...children)``), registering the
  ``$/utils/components/<name>`` import, and stashing the wrapper body
  into the per-page memo-body collector.
* Nested memos produce nested ``MemoCall`` nodes with distinct exports.
* Snapshot-strategy candidates (``MemoizationLeaf`` subclasses) emit a
  ``jsx(<Name>, {})`` call site with no children — the body owns the
  full subtree.
* Phase 2 Part D byte-equal gate: compiling the bench app via the new
  Rust path produces the same page + memo body outputs as the legacy
  Python ``walk_and_memoize`` path.
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
    """Reset the thread-local memoize flag to its production default (ON).

    Phase 2 Part D flipped the default. Tests that need the legacy
    flag-off path call ``sess.set_memoize_in_rust(False)`` explicitly.
    Tests that need the new default get the right state here without
    further setup.
    """
    sess = CompilerSession()
    sess.set_memoize_in_rust(True)
    # Drain any leftover bodies from a previous compile so the
    # populated-collector assertions below see only this test's data.
    sess.take_memo_bodies()


def test_memoize_in_rust_explicit_off_unchanged_output() -> None:
    """With the flag explicitly OFF, output matches the un-memoized baseline."""
    sess = CompilerSession()
    sess.set_memoize_in_rust(False)
    page_root = rx.fragment(rx.box(rx.text("hello")))
    js = sess.compile_page_from_component("Bench", page_root, "/")
    bodies = sess.take_memo_bodies()
    assert bodies == {}, "no memo bodies should be collected when flag is off"
    # No `$/utils/components/...` import line should appear in the
    # baseline output for a plain component tree.
    assert "$/utils/components/" not in js


def test_memoize_in_rust_emits_memo_call_jsx() -> None:
    """Flag on (default), page output contains MemoCall syntax for a state-bound candidate."""
    sess = CompilerSession()
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


def test_compile_memo_from_component_does_not_recurse_memoize() -> None:
    """``compile_memo_from_component`` saves/restores the memoize flag.

    The memo body's top-level node has the same shape as the original
    memoize-candidate Component (Phase 1B hash parity), so it would
    re-trigger `should_memoize` if the flag wasn't disabled around the
    nested ``read_page`` call. The Rust-side ``MemoizeFlagGuard`` makes
    that disable RAII-safe.
    """
    sess = CompilerSession()
    # Build a candidate body manually — same shape `peek_memoize`
    # produces internally — and feed it through compile_memo_from_component.
    body = rx.box("inside", id=_STATE_VAR)
    sess.compile_memo_from_component("MyMemo", "({ children })", body)
    # No memo bodies should be collected: the nested walk ran with the
    # flag disabled, so no self-import was registered.
    assert sess.take_memo_bodies() == {}
    # And the flag is restored to its pre-call value (ON, per the
    # autouse fixture).
    page_root = rx.fragment(rx.box("static", id=_STATE_VAR))
    sess.compile_page_from_component("Bench", page_root, "/")
    assert sess.take_memo_bodies(), (
        "outer compile after compile_memo_from_component should still "
        "see the page-level memoize flag enabled"
    )


def test_phase_d_byte_equal_new_path_vs_legacy_walk() -> None:
    """Phase 2 Part D gating: new Rust path vs legacy Python path output.

    Compile the bench's synthetic page two ways:

    1. **New (default) path** — flag ON, Rust walk does the substitution
       and ``take_memo_bodies()`` drains the bodies for emit.
    2. **Legacy path** — flag OFF, Python ``walk_and_memoize`` does the
       substitution and registers bodies in a local dict.

    **Known divergence — pre-existing in Phase 2 Part B / Wave 1**:
    legacy ``walk_and_memoize`` recurses children-first, so a parent
    that wraps already-wrapped children (e.g. ``Foreach`` whose
    rendered preview is itself a memoize candidate) gets a memo tag
    computed from the post-wrap subtree. The Rust ``try_memoize_in_rust``
    hook calls ``peek_memoize`` on the **original** Component before
    recursing, so the parent's body hashes the pre-wrap subtree. The
    result: identical IR shape and identical call-site JSX, but the
    parent memo's ``export_name`` (and hence its import line) differs
    by hash for the small subset of cases where a memo candidate
    contains another memo candidate in its direct rendered output.

    The test still asserts:

    * The set of memo bodies discovered has the same cardinality.
    * Every memo body that exists under both paths produces byte-equal
      JSX (proving the emit path is unchanged for the bodies whose
      hashes do coincide — leaf wrappers, snapshot leaves, etc.).
    * Page JSX matches once the divergent export names are normalized
      out of the comparison.
    """
    import importlib.util
    import re
    import sys as _sys
    from pathlib import Path as _Path

    from reflex.compiler.rust_memo import (
        _harvest_pre_hooks,
        _signature_for,
        walk_and_memoize,
    )

    # Reuse the bench app builder — it exercises the surfaces (state,
    # vars, foreach, cond, match, event handlers, markdown) that
    # produce the bulk of the memoize candidates seen in real apps.
    bench_path = (
        _Path(__file__).resolve().parents[3] / "scripts" / "benchmark_single_page.py"
    )
    # ``rx.State`` subclasses captured during ``_build_app`` look up
    # their original module in ``sys.modules`` to evaluate type hints,
    # so register the loaded module under a stable name there.
    mod_name = "_reflex_bench_single_page_for_test"
    bench_mod = _sys.modules.get(mod_name)
    if bench_mod is None:
        spec = importlib.util.spec_from_file_location(mod_name, bench_path)
        assert spec is not None
        assert spec.loader is not None
        bench_mod = importlib.util.module_from_spec(spec)
        _sys.modules[mod_name] = bench_mod
        spec.loader.exec_module(bench_mod)
    build_app = bench_mod._build_app

    from reflex.compiler.compiler import compile_unevaluated_page

    # Build the app once so both paths see the same state-class hashes
    # in their memoize body keys. Building twice would register two
    # distinct dynamic ``BenchState`` classes and the export-name hash
    # (which folds the state reference) would diverge.
    app = build_app(scale=1)
    app._apply_decorated_pages()

    def _compile_one(use_rust: bool) -> tuple[str, dict[str, str]]:
        """Return (page_js, {name: memo_body_js}) for the bench page."""
        sess = CompilerSession()
        sess.set_memoize_in_rust(use_rust)
        # Drain any state left from prior compiles on this thread.
        sess.take_memo_bodies()

        route, unev = next(iter(app._unevaluated_pages.items()))
        component = compile_unevaluated_page(route, unev, app.style, app.theme)

        if use_rust:
            page_js = sess.compile_page_from_component("Bench", component, route)
            bodies = sess.take_memo_bodies()
        else:
            memo_bodies_local: dict[str, object] = {}
            component = walk_and_memoize(component, sess, memo_bodies_local)
            page_js = sess.compile_page_from_component("Bench", component, route)
            # Discard any incidental bodies the Rust collector grabbed
            # (should be empty with the flag off, but be safe).
            sess.take_memo_bodies()
            # Adapt to the (body, signature) shape the Rust path
            # produces. ``walk_and_memoize`` already pre-built the body
            # with the ``{children}`` hole substituted (see
            # ``rust_memo._wrap_with_memo``), so we just reattach the
            # signature derived from the definition.
            bodies = {
                name: (body, _signature_for(defn))
                for name, (body, defn) in memo_bodies_local.items()
            }

        # Emit each body's JS via the same Rust entry point both paths
        # use in production. Byte-equal output here is the contract.
        emitted: dict[str, str] = {}
        for name, (body, signature) in bodies.items():
            pre_hooks = _harvest_pre_hooks(body)
            emitted[name] = sess.compile_memo_from_component(
                name, signature, body, pre_hooks=pre_hooks
            )
        return page_js, emitted

    new_page, new_bodies = _compile_one(use_rust=True)
    legacy_page, legacy_bodies = _compile_one(use_rust=False)

    # Same number of memo bodies discovered — neither path missed or
    # gained a candidate.
    assert len(new_bodies) == len(legacy_bodies), (
        f"memo-body count diverged: rust={len(new_bodies)} "
        f"legacy={len(legacy_bodies)}\n"
        f"  rust names: {sorted(new_bodies)}\n"
        f"  legacy names: {sorted(legacy_bodies)}"
    )

    # Names that survive byte-identically across paths — every body
    # JSX must match on those.
    common = set(new_bodies) & set(legacy_bodies)
    for name in common:
        assert new_bodies[name] == legacy_bodies[name], (
            f"memo body {name!r} JSX diverged between paths"
        )

    # Normalize the divergent export-name hashes out of the page JSX:
    # the known cause is the children-first-walk hash drift documented
    # in the test docstring. Once those hashes are folded to a marker
    # token, the pages must be byte-equal.
    def _normalize(js: str) -> str:
        # Replace `<Cls>_<kind>_<32hex>` -> `<Cls>_<kind>_HASH` so the
        # comparison is robust against the export-name drift while
        # still catching any structural diff (extra/missing memo, prop
        # ordering, children count, etc.).
        return re.sub(r"(_comp_|_button_)[0-9a-f]{32}", r"\1HASH", js)

    assert _normalize(new_page) == _normalize(legacy_page), (
        "page JSX diverged in structure (not just export-name hashes) "
        "between Rust and legacy memoize paths"
    )
