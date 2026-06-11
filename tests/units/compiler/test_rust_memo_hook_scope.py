"""Hook ownership across page / memo-body scopes in the Rust pipeline.

A hook must be declared exactly in the function scope whose JSX references
it. Components like reflex-enterprise's dnd attach an instance-specific hook
declaring a CLASS-CONSTANT identifier (``dropTargetCollectedParams``); each
instance is auto-memoized into its own body, so the shared name is legal —
unless the page also hoists every instance's hook into one scope.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("reflex_compiler_rust._native")

from reflex_base.vars.base import Var, VarData

import reflex as rx
from reflex.compiler.session import CompilerSession


class _HookState(rx.State):
    n: int = 0

    def click(self):
        """No-op handler to force memoization of hook divs."""


def _hooked_div(label: str, hook_code: str) -> rx.Component:
    """A div carrying an instance-specific user hook plus an event trigger.

    Mirrors the rxe dnd pattern: the hook rides in a Var's var_data on a
    custom attr, and the event trigger makes the node a memoize candidate.

    Args:
        label: Text child for the div.
        hook_code: The hook source line to attach.

    Returns:
        The component.
    """
    ref_var = Var(_js_expr=f"ref_{label}")._replace(
        merge_var_data=VarData(hooks={hook_code: None})
    )
    return rx.el.div(
        rx.text(label),
        custom_attrs={"ref": ref_var},
        on_click=_HookState.click,
    )


@pytest.fixture(scope="module")
def session() -> CompilerSession:
    """Module-scoped compiler session.

    Returns:
        The session.
    """
    return CompilerSession()


def test_memoized_node_hooks_stay_out_of_page_scope(session: CompilerSession):
    """Per-instance hooks of memoized nodes live in their bodies, not the page.

    Regression: the page hook walk iterated every arena node flat, so two
    drop-target-style instances declared ``const [shared, ...]`` twice in the
    page function — a JS SyntaxError that broke docs enterprise/drag-and-drop.
    """
    comp = rx.box(
        _hooked_div("a", "const [shared, ref_a] = useFakeHook('a');"),
        _hooked_div("b", "const [shared, ref_b] = useFakeHook('b');"),
    )
    comp._add_style_recursive({})
    page_js, bodies, _imports, *_ = session.compile_page_from_component_arena(
        comp, "HookScopePage", "/hook_scope"
    )
    assert page_js.count("useFakeHook(") == 0, page_js
    body_hooks = [body.count("useFakeHook(") for _name, body in bodies]
    assert sorted(body_hooks) == [1, 1], bodies


def test_nested_memo_hooks_stay_out_of_outer_body(session: CompilerSession):
    """A nested memoized node's hooks belong to ITS body, not the ancestor's.

    The outer body renders the nested node as a memo wrapper reference, so
    declaring the inner hook in the outer scope is dead (and collides when
    two nested instances share an identifier).
    """
    inner = _hooked_div("in", "const [shared, ref_in] = useFakeHook('in');")
    outer = _hooked_div("out", "const [outer_p, ref_out] = useOuterHook();")
    outer.children = [*outer.children, inner]
    comp = rx.box(outer)
    comp._add_style_recursive({})
    page_js, bodies, _imports, *_ = session.compile_page_from_component_arena(
        comp, "NestedHookPage", "/nested_hook"
    )
    assert page_js.count("useFakeHook(") == 0
    assert page_js.count("useOuterHook(") == 0
    by_name = dict(bodies)
    outer_bodies = [b for b in by_name.values() if "useOuterHook(" in b]
    assert len(outer_bodies) == 1
    assert outer_bodies[0].count("useFakeHook(") == 0, outer_bodies[0]
    inner_bodies = [b for b in by_name.values() if "useFakeHook(" in b]
    assert len(inner_bodies) == 1


def _wrapper_refs(js: str) -> set[str]:
    """Memo wrapper component names referenced by JSX in ``js``.

    Args:
        js: Emitted module source.

    Returns:
        The referenced wrapper names.
    """
    return set(re.findall(r"jsx\((\w+_memo_[0-9a-f]{16})", js))


def test_modules_import_referenced_memo_wrappers(session: CompilerSession):
    """Every module imports the memo wrappers its JSX references.

    Regression: arena memo wrappers were referenced by name but never
    imported from ``$/utils/components/<name>`` — pages crashed at runtime
    with ``ReferenceError: <X>_memo_<hash> is not defined`` (docs index).
    """
    inner = _hooked_div("in2", "const [shared, ref_in2] = useFakeHook('in2');")
    outer = _hooked_div("out2", "const [outer_p2, ref_out2] = useOuterHook();")
    outer.children = [*outer.children, inner]
    comp = rx.box(outer)
    comp._add_style_recursive({})
    page_js, bodies, _imports, *_ = session.compile_page_from_component_arena(
        comp, "WrapImportPage", "/wrap_import"
    )
    page_refs = _wrapper_refs(page_js)
    assert page_refs, page_js
    for name in page_refs:
        assert f'import {{ {name} }} from "$/utils/components/{name}"' in page_js, (
            page_js
        )
    for body_name, body_js in bodies:
        for name in _wrapper_refs(body_js):
            assert name != body_name
            assert f'import {{ {name} }} from "$/utils/components/{name}"' in body_js, (
                body_js
            )
        # A body must never import itself (collides with its own export).
        assert f"import {{ {body_name} }}" not in body_js, body_js
