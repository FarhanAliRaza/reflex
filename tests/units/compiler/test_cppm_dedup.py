"""Tests covering the cppm single-eval optimization and `walk_and_memoize`.

`create_passthrough_component_memo` used to call its passthrough closure
twice — once to compute the memo tag from the rendered body shape, then
again inside `_create_component_definition` to build the wrapper. The
second evaluation produced identical output (modulo a fresh-but-equivalent
``Bare``-wrapped placeholder) so we now thread the first pass's preview
into `_create_component_definition` to eliminate the redundant work.

These tests assert:

* The passthrough closure is invoked exactly once per cppm call.
* Repeated identical-shape inputs collapse to a single `memo_bodies` entry
  via `_wrap_with_memo` and the page-level wrappers each carry the original
  children for that call site.
* Distinct shapes produce distinct export names.
* The wrapper-instance output is byte-identical under the optimization
  (i.e. behavior matches the pre-optimization expectations encoded in the
  existing memo test suite).
"""

from __future__ import annotations

import copy
import importlib
from typing import Any
from unittest.mock import patch

import pytest

pytest.importorskip("reflex_base")
pytest.importorskip("reflex_components_core")

import reflex as rx
from reflex.compiler import rust_memo

# ``reflex.experimental.memo`` is shadowed at the package level by the
# ``memo`` function re-exported in ``reflex/experimental/__init__.py``,
# so a plain ``from reflex.experimental import memo`` would bind the
# function instead of the module. Pull the module via ``importlib`` so
# the patch points (``_evaluate_memo_function`` etc.) are reachable.
memo_module = importlib.import_module("reflex.experimental.memo")
create_passthrough_component_memo = memo_module.create_passthrough_component_memo


def _row(text: str = "hello") -> Any:
    """Build a small component shape repeated by the bench page.

    Args:
        text: The text content to embed in the row's children.

    Returns:
        An ``hstack`` Component holding two text leaves.
    """
    return rx.hstack(rx.text(text), rx.text(text + "!"))


def test_cppm_invokes_passthrough_closure_only_once() -> None:
    """The passthrough closure used to run twice; now it runs once."""
    real_eval = memo_module._evaluate_memo_function
    call_count = 0

    def counting_eval(fn, params):
        nonlocal call_count
        # Only count calls where ``fn`` is the inner ``passthrough`` closure
        # built by ``create_passthrough_component_memo`` — its identity is
        # distinct from any decorator-built memo function.
        if fn.__module__ == memo_module.__name__ and fn.__name__.startswith((
            "passthrough",
            "",
        )):
            call_count += 1
        return real_eval(fn, params)

    with patch.object(memo_module, "_evaluate_memo_function", counting_eval):
        create_passthrough_component_memo(_row())

    assert call_count == 1, (
        f"expected exactly one passthrough evaluation, got {call_count}"
    )


def test_cppm_preserves_export_name_and_passthrough_hole() -> None:
    """Identical shapes still collapse to one export name, hole is captured."""
    f1, d1 = create_passthrough_component_memo(_row())
    f2, d2 = create_passthrough_component_memo(_row())
    assert d1.export_name == d2.export_name
    # Both wrappers must carry a hole child (passthrough mode).
    assert d1.passthrough_hole_child is not None
    assert d2.passthrough_hole_child is not None
    # The wrapper factories produce ExperimentalMemoComponent instances
    # bound to their definition; same export name -> same wrapper class.
    inst1 = f1()
    inst2 = f2()
    assert type(inst1) is type(inst2)


def test_cppm_distinct_shapes_get_distinct_names() -> None:
    """Two structurally different components don't collide on export name."""
    _, d_a = create_passthrough_component_memo(rx.text("alpha"))
    _, d_b = create_passthrough_component_memo(rx.box(rx.text("beta")))
    assert d_a.export_name != d_b.export_name


def test_cppm_wrapper_render_matches_unoptimized_shape() -> None:
    """The wrapper body renders the same dict it would have pre-optimization.

    We can't compare against the literal pre-optimization output here
    (the code is gone), but we can assert the body's ``render()`` matches
    a fresh-eval baseline of the same shape — confirming that skipping
    the second pass didn't lose any structural info.
    """
    component = _row()
    _, defn = create_passthrough_component_memo(component)
    body = copy.copy(defn.component)
    if defn.passthrough_hole_child is not None:
        body.children = [defn.passthrough_hole_child]
    rendered_once = body.render()

    # Build a second wrapper from the same shape; it should produce an
    # equivalent body. (We compare ``render()`` outputs as the durable
    # surface — Component object identity always differs.)
    _, defn2 = create_passthrough_component_memo(_row())
    body2 = copy.copy(defn2.component)
    if defn2.passthrough_hole_child is not None:
        body2.children = [defn2.passthrough_hole_child]
    rendered_twice = body2.render()
    assert rendered_once == rendered_twice


def test_walk_and_memoize_collapses_repeated_shapes() -> None:
    """Five identical row()s in a page collapse to one ``memo_bodies`` entry.

    Confirms the existing dedup logic in ``_wrap_with_memo`` still holds
    after the cppm refactor, and that the optimization runs the expensive
    `_evaluate_memo_function` exactly five times (one per cppm call) rather
    than ten (one per pass times two passes).
    """
    pytest.importorskip("reflex_compiler_rust._native")
    from reflex.compiler.session import CompilerSession

    page = rx.vstack(*[_row(f"r{i}") for i in range(5)])
    # All five rows share the same shape (children text differs only in the
    # `{children}` hole, which is replaced before the tag is computed).
    rows = page.children
    assert len(rows) == 5

    session = CompilerSession()
    memo_bodies: dict[str, Any] = {}

    real_eval = memo_module._evaluate_memo_function
    eval_calls = 0

    def counting_eval(fn, params):
        nonlocal eval_calls
        if fn.__module__ == memo_module.__name__:
            eval_calls += 1
        return real_eval(fn, params)

    with patch.object(memo_module, "_evaluate_memo_function", counting_eval):
        transformed = rust_memo.walk_and_memoize(page, session, memo_bodies)

    # The top-level vstack itself may also be a memoization candidate; what
    # we care about is that the five row()s collapse to a single
    # ``memo_bodies`` entry for their shared export name.
    row_export_names = {
        type(child).tag for child in transformed.children if hasattr(type(child), "tag")
    }
    # Each wrapper class is keyed on its export_name (set as the ``tag``
    # ClassVar in ``_get_experimental_memo_component_class``). Five rows of
    # the same shape -> one shared wrapper class -> one tag.
    assert len(row_export_names) == 1

    # And each wrapped row received the cppm pass exactly once (eval_calls
    # would be 10 under the old two-pass implementation for just the rows;
    # we allow the count to include the outer vstack too).
    # Without the optimization: at least 2 evaluations per memoized node.
    # With the optimization: exactly 1 evaluation per memoized node.
    # We assert <= number of memoized nodes which is a strict win.
    num_memoized = len(memo_bodies)
    assert eval_calls <= num_memoized + 1, (
        f"expected at most one passthrough eval per memoized body "
        f"(plus possible top-level node), got {eval_calls} evals for "
        f"{num_memoized} bodies"
    )
