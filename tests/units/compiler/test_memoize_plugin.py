# ruff: noqa: D101

import dataclasses
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from reflex_base.components.component import Component, field
from reflex_base.components.memoize_helpers import (
    MemoizationStrategy,
    get_memoization_strategy,
)
from reflex_base.constants.compiler import MemoizationDisposition, MemoizationMode
from reflex_base.plugins import CompileContext, CompilerHooks, PageContext
from reflex_base.vars import VarData
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.base.bare import Bare
from reflex_components_core.base.fragment import Fragment

import reflex as rx
import reflex.compiler.plugins.memoize as memoize_plugin
from reflex.compiler.plugins import DefaultCollectorPlugin, default_page_plugins
from reflex.compiler.plugins.memoize import MemoizeStatefulPlugin, _should_memoize
from reflex.experimental.memo import (
    ExperimentalMemoComponent,
    create_passthrough_component_memo,
)
from reflex.state import BaseState

STATE_VAR = LiteralVar.create("value")._replace(
    merge_var_data=VarData(hooks={"useTestState": None}, state="TestState")
)


class Plain(Component):
    tag = "Plain"
    library = "plain-lib"


class WithProp(Component):
    tag = "WithProp"
    library = "with-prop-lib"

    label: Var[str] = field(default=LiteralVar.create(""))


class LeafComponent(Component):
    tag = "LeafComponent"
    library = "leaf-lib"
    _memoization_mode = MemoizationMode(recursive=False)


class SpecialFormMemoState(BaseState):
    items: list[str] = ["a"]
    flag: bool = True
    value: str = "a"


@dataclasses.dataclass(slots=True)
class FakePage:
    route: str
    component: Callable[[], Component]
    title: Any = None
    description: Any = None
    image: str = ""
    meta: tuple[dict[str, Any], ...] = ()


def _compile_single_page(
    component_factory: Callable[[], Component],
) -> tuple[CompileContext, PageContext]:
    ctx = CompileContext(
        pages=[FakePage(route="/p", component=component_factory)],
        hooks=CompilerHooks(plugins=default_page_plugins()),
    )
    with ctx:
        ctx.compile()
    return ctx, ctx.compiled_pages["/p"]


def test_should_memoize_catches_direct_state_var_in_prop() -> None:
    """A component whose own prop carries state VarData should memoize."""
    comp = WithProp.create(label=STATE_VAR)
    assert _should_memoize(comp)


def test_should_not_memoize_state_var_in_child_bare() -> None:
    """A component whose Bare child contains state VarData should memoize."""
    comp = Plain.create(STATE_VAR)
    assert not _should_memoize(comp)


def test_should_not_memoize_plain_component() -> None:
    """A component with no state vars and no event triggers is not memoized."""
    comp = Plain.create(LiteralVar.create("static-content"))
    assert not _should_memoize(comp)


def test_should_memoize_state_var_in_child_cond() -> None:
    """A Bare containing state VarData should memoize."""
    comp = Bare.create(STATE_VAR)
    assert _should_memoize(comp)


def test_should_not_memoize_when_disposition_never() -> None:
    """``MemoizationDisposition.NEVER`` overrides heuristic eligibility."""
    comp = Plain.create(STATE_VAR)
    object.__setattr__(
        comp,
        "_memoization_mode",
        dataclasses.replace(
            comp._memoization_mode, disposition=MemoizationDisposition.NEVER
        ),
    )
    assert not _should_memoize(comp)


def test_memoize_wrapper_uses_experimental_memo_component_and_call_site() -> None:
    """Memoizable component imports a generated ``rx._x.memo`` wrapper."""
    ctx, page_ctx = _compile_single_page(lambda: Plain.create(STATE_VAR))

    assert len(ctx.memoize_wrappers) == 1
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    assert wrapper_tag in ctx.auto_memo_components
    output = page_ctx.output_code or ""
    assert f'import {{{wrapper_tag}}} from "$/utils/components/{wrapper_tag}"' in output
    assert f"jsx({wrapper_tag}," in (page_ctx.output_code or "")
    assert f"const {wrapper_tag} = memo" not in output


def test_memoize_wrapper_deduped_across_repeated_subtrees() -> None:
    """Two identical memoizable call-sites collapse to one memo definition."""
    ctx, page_ctx = _compile_single_page(
        lambda: Fragment.create(
            Plain.create(STATE_VAR),
            Plain.create(STATE_VAR),
        )
    )
    assert len(ctx.memoize_wrappers) == 1
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    assert list(ctx.auto_memo_components) == [wrapper_tag]
    assert (page_ctx.output_code or "").count(
        f'import {{{wrapper_tag}}} from "$/utils/components/{wrapper_tag}"'
    ) == 1


@pytest.mark.parametrize(
    ("special_form", "body_marker"),
    [
        ("foreach", "Array.prototype.map.call"),
    ],
)
def test_special_form_memo_wrappers_render_structural_body(
    special_form: str,
    body_marker: str,
) -> None:
    """Generated memo wrappers for special forms render the structural body.

    The memo body must subscribe to the state the special form references
    (via ``useContext(StateContexts...)``), and the page must not — otherwise
    the state-dependent render has leaked into page scope.
    """
    from reflex.compiler.compiler import compile_memo_components

    def special_child() -> Component:
        if special_form == "foreach":
            return rx.foreach(
                SpecialFormMemoState.items,
                lambda item: rx.text(item),
            )
        if special_form == "cond":
            return cast(
                Component,
                rx.cond(
                    SpecialFormMemoState.flag,
                    rx.text("yes"),
                    rx.text("no"),
                ),
            )
        return cast(
            Component,
            rx.match(
                SpecialFormMemoState.value,
                ("a", rx.text("A")),
                rx.text("default"),
            ),
        )

    ctx, page_ctx = _compile_single_page(lambda: rx.box(special_child()))

    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    memo_code = "\n".join(code for _, code in memo_files)

    state_wiring = "useContext(StateContexts"
    assert state_wiring in memo_code
    assert state_wiring not in (page_ctx.output_code or "")
    assert body_marker in memo_code
    assert body_marker not in (page_ctx.output_code or "")


def test_common_memoization_snapshot_helper_classifies_snapshot_cases() -> None:
    """The shared memoization strategy classifies structural render forms."""
    from reflex_components_core.core.cond import Cond
    from reflex_components_core.core.match import Match
    from reflex_components_core.el.elements.forms import Form, Input

    foreach_parent = rx.box(
        rx.foreach(
            SpecialFormMemoState.items,
            lambda item: rx.text(item),
        )
    )
    cond_fragment = cast(
        Component,
        rx.cond(
            SpecialFormMemoState.flag,
            rx.text("yes"),
            rx.text("no"),
        ),
    )
    match_fragment = cast(
        Component,
        rx.match(
            SpecialFormMemoState.value,
            ("a", rx.text("A")),
            rx.text("default"),
        ),
    )

    assert get_memoization_strategy(foreach_parent) is MemoizationStrategy.SNAPSHOT
    assert get_memoization_strategy(cond_fragment) is MemoizationStrategy.PASSTHROUGH
    # Cond and Match now use passthrough so branch JSX renders on the page side
    # and the memo body just selects via children[i] indexing.
    assert isinstance(cond_fragment.children[0], Cond)
    assert (
        get_memoization_strategy(cond_fragment.children[0])
        is MemoizationStrategy.PASSTHROUGH
    )
    assert isinstance(match_fragment.children[0], Match)
    assert (
        get_memoization_strategy(match_fragment.children[0])
        is MemoizationStrategy.PASSTHROUGH
    )
    assert (
        get_memoization_strategy(LeafComponent.create(Plain.create()))
        is MemoizationStrategy.SNAPSHOT
    )

    form = Form.create(Input.create(name="username", id="username"))
    assert get_memoization_strategy(form) is MemoizationStrategy.PASSTHROUGH


def test_memoization_leaf_suppresses_descendant_wrapping() -> None:
    """A MemoizationLeaf suppresses independent wrappers for its descendants.

    Even when a descendant (``Plain(STATE_VAR)``) would otherwise be wrapped,
    being inside a leaf's subtree suppresses that wrapping. Whether or not the
    leaf itself gets wrapped, descendants do not produce their own wrappers.
    """
    ctx, _page_ctx = _compile_single_page(
        lambda: LeafComponent.create(
            Plain.create(STATE_VAR),  # would otherwise be independently memoized
        )
    )
    # The inner Plain(STATE_VAR) is suppressed because it's inside the leaf's
    # subtree. The leaf itself has no direct state dependency so no wrapper
    # is emitted for it either.
    assert len(ctx.memoize_wrappers) == 0


def test_generated_memo_component_is_not_itself_memoized() -> None:
    """The generated memo component instance itself is skipped by the heuristic."""
    wrapper_factory, _definition = create_passthrough_component_memo(
        "MyTag", Fragment.create()
    )
    wrapper = wrapper_factory(Plain.create())
    assert isinstance(wrapper, ExperimentalMemoComponent)
    assert not _should_memoize(wrapper)


def test_event_trigger_memoization_not_emit_usecallback_in_page_hooks() -> None:
    """Components with event triggers do not get useCallback wrappers at the page level."""
    from reflex_base.event import EventChain

    # Construct an event chain referencing state so _get_memoized_event_triggers
    # emits a useCallback.
    event_var = Var(_js_expr="test_event")._replace(
        _var_type=EventChain,
        merge_var_data=VarData(state="TestState"),
    )
    comp = Plain.create()
    comp.event_triggers["on_click"] = event_var

    _ctx, page_ctx = _compile_single_page(lambda: comp)

    # Check that a useCallback hook line was added to the page hooks dict.
    hook_lines = list(page_ctx.hooks.keys())
    assert not any(
        "useCallback" in hook_line and "on_click_" in hook_line
        for hook_line in hook_lines
    ), f"Expected no on_click useCallback hook in {hook_lines!r}"


def test_generated_memo_component_renders_as_its_exported_tag() -> None:
    """The generated experimental memo component renders as its exported tag."""
    wrapper_factory, definition = create_passthrough_component_memo(
        "MyWrapper_abc", Fragment.create()
    )
    wrapper = wrapper_factory(Plain.create())
    assert isinstance(wrapper, ExperimentalMemoComponent)
    assert wrapper.tag == "MyWrapper_abc"
    assert definition.export_name == "MyWrapper_abc"
    assert wrapper.render()["name"] == "MyWrapper_abc"


def test_passthrough_memo_definitions_are_not_shared_globally(monkeypatch) -> None:
    """Repeated tags across compiles rebuild their passthrough definitions.

    Regression: sharing auto-memo definitions globally by tag leaks the first
    app's captured component tree into later compiles, which can stale-bind
    state event names across AppHarness apps.
    """
    tag = "SharedMemoTag"
    first_component = Plain.create(STATE_VAR)
    second_component = Plain.create(STATE_VAR)

    monkeypatch.setattr(memoize_plugin, "_compute_memo_tag", lambda comp: tag)
    monkeypatch.setattr(
        memoize_plugin,
        "fix_event_triggers_for_memo",
        lambda comp, page_context: comp,
    )

    def fake_create_passthrough_component_memo(
        export_name: str,
        component: Component,
    ):
        definition = SimpleNamespace(export_name=export_name, component=component)
        return (lambda definition=definition: definition), definition

    monkeypatch.setattr(
        memoize_plugin,
        "create_passthrough_component_memo",
        fake_create_passthrough_component_memo,
    )

    first_compile = SimpleNamespace(memoize_wrappers={}, auto_memo_components={})
    second_compile = SimpleNamespace(memoize_wrappers={}, auto_memo_components={})
    page_context = cast(PageContext, SimpleNamespace())

    MemoizeStatefulPlugin._build_wrapper(
        first_component,
        page_context=page_context,
        compile_context=first_compile,
    )
    MemoizeStatefulPlugin._build_wrapper(
        second_component,
        page_context=page_context,
        compile_context=second_compile,
    )

    first_definition = first_compile.auto_memo_components[tag]
    second_definition = second_compile.auto_memo_components[tag]
    assert first_definition.component is first_component
    assert second_definition.component is second_component
    assert second_definition is not first_definition


def test_shared_subtree_across_pages_uses_same_tag() -> None:
    """The same memoizable subtree on multiple pages gets one shared tag."""
    ctx = CompileContext(
        pages=[
            FakePage(route="/a", component=lambda: Plain.create(STATE_VAR)),
            FakePage(route="/b", component=lambda: Plain.create(STATE_VAR)),
        ],
        hooks=CompilerHooks(plugins=default_page_plugins()),
    )
    with ctx:
        ctx.compile()

    assert len(ctx.memoize_wrappers) == 1
    tag = next(iter(ctx.memoize_wrappers))
    assert list(ctx.auto_memo_components) == [tag]
    for route in ("/a", "/b"):
        output = ctx.compiled_pages[route].output_code or ""
        assert f'import {{{tag}}} from "$/utils/components/{tag}"' in output
        assert f"jsx({tag}," in output


def test_shared_parent_instance_across_pages_preserves_original() -> None:
    """A parent instance reused across pages must not have its children rebound.

    Regression: the compile walker replaces memoizable descendants with memo
    wrappers and writes the new children list onto their parent. If the parent
    is the same Python object on two pages (e.g. a module-scope layout), page
    A's compile would mutate page B's starting tree, producing a ``ReferenceError``
    for the memo tag on the second page.
    """
    shared_parent = Fragment.create(WithProp.create(label=STATE_VAR))
    original_children = list(shared_parent.children)
    original_child = shared_parent.children[0]

    ctx = CompileContext(
        pages=[
            FakePage(route="/a", component=lambda: shared_parent),
            FakePage(route="/b", component=lambda: shared_parent),
        ],
        hooks=CompilerHooks(plugins=default_page_plugins()),
    )
    with ctx:
        ctx.compile()

    assert shared_parent.children == original_children, (
        f"shared parent's children mutated: {shared_parent.children!r}"
    )
    assert shared_parent.children[0] is original_child, (
        "shared parent's child reference replaced by a memo wrapper"
    )

    assert len(ctx.memoize_wrappers) == 1
    tag = next(iter(ctx.memoize_wrappers))
    for route in ("/a", "/b"):
        output = ctx.compiled_pages[route].output_code or ""
        assert f'import {{{tag}}} from "$/utils/components/{tag}"' in output, (
            f"route {route} missing memo tag import"
        )
        assert f"jsx({tag}," in output, f"route {route} does not render the memo tag"


def test_shared_nested_parent_mirroring_common_elements_preserves_original() -> None:
    """Deeper nested shape — mirrors ``common_elements`` in test_event_chain.

    ``common_elements`` is an outer ``rx.vstack`` that contains an inner
    ``rx.vstack(rx.foreach(...))`` memoizable subtree. The walker must clone
    the entire spine from the memoized descendant up to the shared root, not
    just the immediate parent.
    """
    inner_parent = Fragment.create(WithProp.create(label=STATE_VAR))
    shared_outer = Fragment.create(
        WithProp.create(label=LiteralVar.create("static")),
        inner_parent,
        WithProp.create(label=LiteralVar.create("trailing")),
    )
    original_outer_children = list(shared_outer.children)
    original_inner = shared_outer.children[1]
    original_inner_children = list(inner_parent.children)
    original_innermost = inner_parent.children[0]

    ctx = CompileContext(
        pages=[
            FakePage(route="/a", component=lambda: shared_outer),
            FakePage(route="/b", component=lambda: shared_outer),
            FakePage(route="/c", component=lambda: shared_outer),
        ],
        hooks=CompilerHooks(plugins=default_page_plugins()),
    )
    with ctx:
        ctx.compile()

    assert shared_outer.children == original_outer_children
    assert shared_outer.children[1] is original_inner
    assert inner_parent.children == original_inner_children
    assert inner_parent.children[0] is original_innermost

    assert len(ctx.memoize_wrappers) == 1
    tag = next(iter(ctx.memoize_wrappers))
    for route in ("/a", "/b", "/c"):
        output = ctx.compiled_pages[route].output_code or ""
        assert f'import {{{tag}}} from "$/utils/components/{tag}"' in output
        assert f"jsx({tag}," in output


def test_memoization_leaf_internal_hooks_do_not_leak_into_page() -> None:
    """Hooks from a ``MemoizationLeaf``'s internal children stay in its memo body.

    ``MemoizationLeaf``-derived components (e.g. ``rx.upload.root``) build
    internal machinery as their own structural children, attaching stateful
    hooks via ``special_props``/``VarData``. Those hooks belong to the memo
    component's function body — not to the page — because the whole point of
    the leaf is to isolate its subtree from page-level re-renders.

    The test asserts both directions: the hook lines do not appear in the
    page's collected hooks, *and* they do appear in the compiled memo module
    (otherwise a regression that drops them entirely would pass the negative
    check).
    """
    from reflex_base.components.component import MemoizationLeaf
    from reflex_base.event import EventChain
    from reflex_base.vars.base import Var

    from reflex.compiler.compiler import compile_memo_components

    class StatefulLeaf(MemoizationLeaf):
        tag = "StatefulLeaf"
        library = "stateful-leaf-lib"

        @classmethod
        def create(cls, *children, **props):
            # Simulate what rx.upload.root does: build an internal child whose
            # special_props carry stateful hook lines via VarData.
            internal_hook_var = Var(
                _js_expr="__internal_leaf_probe()",
                _var_type=None,
                _var_data=VarData(
                    hooks={
                        "const __internal_leaf_probe = useLeafProbe();": None,
                        "const on_drop_xyz = useCallback(() => {}, []);": None,
                    },
                    state="LeafState",
                ),
            )
            internal_child = Plain.create(*children)
            internal_child.special_props = [internal_hook_var]
            return super().create(internal_child, **props)

    stateful_event = Var(_js_expr="evt")._replace(
        _var_type=EventChain,
        merge_var_data=VarData(state="LeafState"),
    )
    leaf = StatefulLeaf.create()
    leaf.event_triggers["on_something"] = stateful_event

    ctx, page_ctx = _compile_single_page(lambda: leaf)

    page_hook_lines = list(page_ctx.hooks)
    leaking_hooks = [
        hook
        for hook in page_hook_lines
        if "useLeafProbe" in hook or "on_drop_xyz" in hook
    ]
    assert not leaking_hooks, (
        f"MemoizationLeaf internal hooks leaked into page: {leaking_hooks!r}"
    )

    # The hooks must survive somewhere — in the compiled memo module for the
    # generated leaf wrapper. Compile the auto-memo definitions collected
    # during the page compile and check that the hook lines are present.
    assert ctx.auto_memo_components, (
        "expected an auto-memo wrapper to be generated for the leaf"
    )
    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    memo_code = "\n".join(code for _, code in memo_files)
    assert "useLeafProbe" in memo_code, (
        "leaf's internal probe hook was dropped from the memo module"
    )
    assert "on_drop_xyz" in memo_code, (
        "leaf's internal useCallback hook was dropped from the memo module"
    )


def test_plugin_only_registered_once_in_default_page_plugins() -> None:
    """MemoizeStatefulPlugin appears exactly once in the default plugin pipeline."""
    plugins = default_page_plugins()
    memoize_plugins = [p for p in plugins if isinstance(p, MemoizeStatefulPlugin)]
    assert len(memoize_plugins) == 1
    # And it is registered after the DefaultCollectorPlugin.
    collector_index = next(
        i for i, p in enumerate(plugins) if isinstance(p, DefaultCollectorPlugin)
    )
    memoize_index = plugins.index(memoize_plugins[0])
    assert memoize_index > collector_index


def test_match_non_stateful_cond_allows_stateful_children_to_memoize() -> None:
    """Match with a non-stateful condition must not suppress child memoization.

    Regression: Match was a MemoizationLeaf, causing it to push onto the
    suppressor stack when its condition had no VarData. That blocked
    independently-stateful children from being wrapped. After the fix Match
    is a plain Component and its stateful children are memoized normally.
    """

    def page() -> Component:
        comp = rx.match(
            "static",  # non-stateful condition
            ("a", WithProp.create(label=STATE_VAR)),
            WithProp.create(label=LiteralVar.create("default")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, _page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected the stateful WithProp inside match cases to be memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )


def test_cond_non_stateful_cond_allows_stateful_children_to_memoize() -> None:
    """Cond with a non-stateful condition must not suppress child memoization.

    When the condition carries no VarData, Cond should not be extracted to its
    own memo component. Its stateful children (comp1 / comp2) should still be
    independently memoized.
    """

    def page() -> Component:
        comp = rx.cond(
            True,  # non-stateful condition
            WithProp.create(label=STATE_VAR),
            WithProp.create(label=LiteralVar.create("false-branch")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, _page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected the stateful WithProp inside cond branch to be memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )


def test_cond_and_match_strategy_classification() -> None:
    """Cond and Match both use passthrough; branches render on the page side."""
    from reflex_components_core.core.cond import Cond
    from reflex_components_core.core.match import Match

    cond_non_stateful = rx.cond(
        True,
        rx.text("yes"),
        rx.text("no"),
    )
    cond_stateful = rx.cond(
        SpecialFormMemoState.flag,
        rx.text("yes"),
        rx.text("no"),
    )
    match_non_stateful = rx.match(
        "static",
        ("a", rx.text("A")),
        rx.text("default"),
    )
    match_stateful = rx.match(
        SpecialFormMemoState.value,
        ("a", rx.text("A")),
        rx.text("default"),
    )

    for comp in (cond_non_stateful, cond_stateful):
        assert isinstance(comp, Component)
        assert get_memoization_strategy(comp) is MemoizationStrategy.PASSTHROUGH
        assert isinstance(comp.children[0], Cond)
        assert (
            get_memoization_strategy(comp.children[0])
            is MemoizationStrategy.PASSTHROUGH
        )

    for comp in (match_non_stateful, match_stateful):
        assert isinstance(comp, Component)
        assert isinstance(comp.children[0], Match)
        assert (
            get_memoization_strategy(comp.children[0])
            is MemoizationStrategy.PASSTHROUGH
        )


def test_cond_stateful_var_branch_memoized_as_bare() -> None:
    """rx.cond(True, STATE_VAR, "false") embeds a stateful ternary Var in a Bare.

    The ternary Var produced by the Var-returning cond path carries STATE_VAR's
    VarData. When rendered inside rx.box it appears as a Bare child, which must
    be extracted into its own memoized component.
    """
    ctx, _page_ctx = _compile_single_page(
        lambda: rx.box(rx.cond(True, STATE_VAR, "false")),
    )
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected stateful cond ternary var to produce one memoized Bare, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )


def test_cond_stateful_condition_memoizes_whole_cond_and_stateful_branch() -> None:
    """Stateful Cond condition memoizes both Cond and stateful branch.

    Cond should recurse into branches so stateful branch components are wrapped
    independently, while the Cond itself is also wrapped because its condition
    var reads state.
    """

    def page() -> Component:
        comp = rx.cond(
            SpecialFormMemoState.flag,
            WithProp.create(label=STATE_VAR),
            WithProp.create(label=LiteralVar.create("false-branch")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, _page_ctx = _compile_single_page(page)

    assert len(ctx.memoize_wrappers) == 2, (
        "Expected both Cond and its stateful branch component to be memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tags = tuple(ctx.memoize_wrappers)
    assert any("cond" in tag.lower() for tag in wrapper_tags)
    assert any("withprop" in tag.lower() for tag in wrapper_tags)


def test_match_stateful_condition_memoizes_whole_match_and_stateful_branch() -> None:
    """Stateful Match condition memoizes both Match and stateful branch.

    Match should recurse into branches so stateful branch components are
    memoized independently, while Match itself is memoized when its condition
    var carries VarData.
    """

    def page() -> Component:
        comp = rx.match(
            SpecialFormMemoState.value,
            ("a", WithProp.create(label=STATE_VAR)),
            WithProp.create(label=LiteralVar.create("default")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, _page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 2, (
        "Expected both Match and its stateful branch component to be memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tags = tuple(ctx.memoize_wrappers)
    assert any("match" in tag.lower() for tag in wrapper_tags)
    assert any("withprop" in tag.lower() for tag in wrapper_tags)


def test_cond_stateful_branch_component_renders_via_memoized_wrapper() -> None:
    """Components inside Cond branches must render via their memo wrappers.

    Regression shape matching the Match case: when the walker memoizes a
    branch component, Cond rendering must use the wrapped branch tag in page
    output rather than the original unwrapped component tag.
    """

    def page() -> Component:
        comp = rx.cond(
            True,
            WithProp.create(label=STATE_VAR),
            WithProp.create(label=LiteralVar.create("false-branch")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected stateful branch to produce one memo wrapper, got: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    output = page_ctx.output_code or ""
    assert f"jsx({wrapper_tag}," in output, (
        f"Memo wrapper {wrapper_tag!r} not found in page output.\n"
        f"Output snippet: {output[:2000]}"
    )


def test_cond_stateful_condition_renders_branch_logic_in_memo_body() -> None:
    """Stateful Cond memo body must select both branches via ``children`` indexing.

    Cond is now a passthrough wrapper: branch JSX is rendered on the page side
    and passed as the ``children`` array. The memo body's ternary must select
    ``children[0]`` for the true branch and ``children[1]`` for the false
    branch — neither branch should collapse to a generic ``? children`` hole
    nor inline the original branch text into the memo body.
    """
    from reflex.compiler.compiler import compile_memo_components

    def page() -> Component:
        comp = rx.cond(
            SpecialFormMemoState.flag,
            rx.text("yes"),
            rx.text("no"),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected stateful Cond to produce one memo wrapper, got: {list(ctx.memoize_wrappers)}"
    )

    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    memo_code = "\n".join(code for _, code in memo_files)

    assert "children?.at?.(0)" in memo_code, (
        "Cond memo body should select the true branch via children[0].\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert "children?.at?.(1)" in memo_code, (
        "Cond memo body should select the false branch via children[1].\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert '"yes"' not in memo_code, (
        "Cond memo body unexpectedly inlined the true branch.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert '"no"' not in memo_code, (
        "Cond memo body unexpectedly inlined the false branch.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )

    page_output = page_ctx.output_code or ""
    assert '"yes"' in page_output, (
        "Page output should render the true branch as a memo wrapper child.\n"
        f"Page output snippet: {page_output[:2000]}"
    )
    assert '"no"' in page_output, (
        "Page output should render the false branch as a memo wrapper child.\n"
        f"Page output snippet: {page_output[:2000]}"
    )


def test_match_stateful_branch_component_renders_via_memoized_wrapper() -> None:
    """Components inside Match branches must be rendered via their memo wrappers.

    Regression: Match._render() used self.match_cases / self.default directly
    instead of self.children. The walker updates children when it memoizes a
    branch component, but those updates were invisible to Match's render, so
    the generated page JSX still referenced the original unwrapped component
    tag rather than the memo wrapper.
    """

    def page() -> Component:
        comp = rx.match(
            "static",
            ("a", WithProp.create(label=STATE_VAR)),
            WithProp.create(label=LiteralVar.create("default")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected stateful branch to produce one memo wrapper, got: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    output = page_ctx.output_code or ""
    assert f"jsx({wrapper_tag}," in output, (
        f"Memo wrapper {wrapper_tag!r} not found in page output.\n"
        f"Output snippet: {output[:2000]}"
    )


def test_match_stateful_condition_uses_memoized_branch_wrapper_in_memo_body() -> None:
    """Stateful Match passes branch wrappers as page-side children.

    Match is now a passthrough wrapper: when both the match condition and a
    branch are stateful, the Match wrapper itself is memoized and the branch
    is memoized separately. The Match memo body selects via ``children[i]``
    indexing, and the page output renders the branch wrapper as a child of
    the Match wrapper (rather than inlining the unwrapped branch component).
    """
    from reflex.compiler.compiler import compile_memo_components

    def page() -> Component:
        comp = rx.match(
            SpecialFormMemoState.value,
            ("a", WithProp.create(label=STATE_VAR)),
            WithProp.create(label=LiteralVar.create("default")),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 2, (
        "Expected both Match and its stateful branch component to be memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )

    match_wrapper_tag = next(
        tag for tag in ctx.memoize_wrappers if "match" in tag.lower()
    )
    branch_wrapper_tag = next(
        tag for tag in ctx.memoize_wrappers if "withprop" in tag.lower()
    )

    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    match_memo_code = next(
        code
        for path, code in memo_files
        if Path(path).name == f"{match_wrapper_tag}.jsx"
    )

    assert "children?.at?.(0)" in match_memo_code, (
        "Match memo body should select case 0 via children indexing.\n"
        f"Memo code snippet: {match_memo_code[:2000]}"
    )
    assert "children?.at?.(1)" in match_memo_code, (
        "Match memo body should select the default via children indexing.\n"
        f"Memo code snippet: {match_memo_code[:2000]}"
    )
    assert f"jsx({branch_wrapper_tag}," not in match_memo_code, (
        "Match memo body should not inline the branch wrapper; the branch "
        "renders on the page side as a memo wrapper child.\n"
        f"Memo code snippet: {match_memo_code[:2000]}"
    )

    page_output = page_ctx.output_code or ""
    assert f"jsx({match_wrapper_tag}," in page_output, (
        f"Page output should render the Match memo wrapper {match_wrapper_tag!r}.\n"
        f"Output snippet: {page_output[:2000]}"
    )
    assert f"jsx({branch_wrapper_tag}," in page_output, (
        f"Page output should render the branch memo wrapper {branch_wrapper_tag!r} "
        "as a child of the Match wrapper.\n"
        f"Output snippet: {page_output[:2000]}"
    )


def test_memoized_match_wrapper_receives_case_children_in_page_output() -> None:
    """Passthrough Match wrapper receives all case children from the page output.

    With Match handled as a passthrough memo, the page renders each case's JSX
    as a child of the Match wrapper. The memo body selects which child to mount
    via ``children[i]`` indexing keyed on the (possibly stateful) condition.
    """

    def page() -> Component:
        comp = rx.match(
            SpecialFormMemoState.value,
            ("a", rx.text("A")),
            ("b", rx.text("B")),
            rx.text("default"),
        )
        assert isinstance(comp, Component)
        return comp

    ctx, page_ctx = _compile_single_page(page)
    assert len(ctx.memoize_wrappers) == 1, (
        f"Expected stateful Match to produce one memo wrapper, got: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    output = page_ctx.output_code or ""

    assert f"jsx({wrapper_tag}," in output, (
        f"Memo wrapper {wrapper_tag!r} not found in page output.\n"
        f"Output snippet: {output[:2000]}"
    )
    # Each case-return JSX, plus the default, must reach the wrapper as a child.
    for case_text in ('"A"', '"B"', '"default"'):
        assert case_text in output, (
            f"Expected case JSX {case_text} in page output as a Match wrapper child.\n"
            f"Output snippet: {output[:2000]}"
        )
    # Match wrapper must be called with three positional children (the cases plus
    # default), not as an empty-children call.
    assert re.search(
        rf"jsx\({re.escape(wrapper_tag)},\s*\{{\}},\s*jsx\(",
        output,
    ), (
        "Match wrapper should receive case JSX as positional children in page output.\n"
        f"Output snippet: {output[:2000]}"
    )


def test_client_state_setter_in_call_function_event_imports_refs() -> None:
    """A button whose ``on_click`` calls a global ``ClientStateVar`` setter
    must memoize and the resulting memo body's imports must include ``refs``
    from ``$/utils/state``.

    Regression: ``ClientStateVar.set_value`` builds its setter as
    ``refs['_client_state_<setter>']`` but the returned setter ``Var`` does not
    carry the ``refs`` import. When the on_click event chain is compiled into
    the memo body, the body references ``refs['_client_state_<setter>'](42)``
    with no matching ``import { refs } from "$/utils/state"`` — producing a
    ``ReferenceError: refs is not defined`` at runtime.
    """
    from reflex.compiler.compiler import compile_memo_components
    from reflex.experimental.client_state import ClientStateVar

    counter = ClientStateVar.create("counter", default=0)

    def page() -> Component:
        return rx.el.button(
            "click",
            on_click=rx.call_function(counter.set_value(42)),
        )

    ctx, _page_ctx = _compile_single_page(page)

    assert len(ctx.memoize_wrappers) == 1, (
        "Expected the button with a stateful on_click to be auto-memoized, "
        f"got wrappers: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tag = next(iter(ctx.memoize_wrappers))

    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    memo_code = next(
        code for path, code in memo_files if Path(path).name == f"{wrapper_tag}.jsx"
    )

    assert "refs['_client_state_setCounter'](42)" in memo_code, (
        "Expected the memo body to call the client-state setter via refs.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )

    state_import_match = re.search(
        r'^import\s*\{([^}]*)\}\s*from\s*"\$/utils/state"',
        memo_code,
        flags=re.MULTILINE,
    )
    assert state_import_match is not None, (
        "Memo body must import from $/utils/state since the on_click handler "
        "uses refs['_client_state_setCounter'].\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    imported_names = {name.strip() for name in state_import_match.group(1).split(",")}
    assert "refs" in imported_names, (
        f"Memo body imports {imported_names!r} from $/utils/state but is missing "
        "'refs' — the on_click handler references refs['_client_state_setCounter'].\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )


def test_debounce_input_memo_renders_react_debounce_wrapper() -> None:
    """``rx.input(value=..., on_change=..., debounce_timeout=N)`` memoizes via DebounceInput.

    When ``rx.input`` is given both ``value`` and ``on_change`` it is wrapped by
    ``DebounceInput`` so the underlying input is fully controlled without typing
    jank. The wrapper carries DebounceInput-known props (``debounce_timeout``,
    ``input_ref``, ``element``) and also forwards the inner TextField as the
    ``element`` prop. The memo body produced by the auto-memoize plugin must:

    - Import ``DebounceInput`` from ``react-debounce-input`` and render it via
      ``jsx(DebounceInput, ...)`` rather than rendering the inner TextField
      directly. The whole point of the wrapping is to give react-debounce-input
      ownership of the keystroke pipeline; if the memo emitted the inner
      ``TextField.Root`` instead, controlled-input updates would race the
      backend round-trip and drop characters.
    - Pass ``debounceTimeout`` as a real DebounceInput prop, not via ``css``.
      Reflex routes unknown TextFieldRoot kwargs (like ``debounce_timeout``)
      into ``style`` at component construction; ``DebounceInput.create`` then
      copies ``child.style`` into the wrapper, which can leak the timeout into
      the rendered ``css`` block. The timeout belongs on the wrapper as a real
      prop — leaking it to ``css`` makes it a no-op styling key while the real
      debounce behavior depends on the prop alone.
    - Wire ``element`` to ``RadixThemesTextField.Root`` so the underlying input
      is the radix text field and not a bare ``<input>``.
    """
    from reflex.compiler.compiler import compile_memo_components

    class DebounceState(BaseState):
        value: str = ""

        @rx.event
        def set_value(self, v: str) -> None:
            self.value = v

    def page() -> Component:
        return rx.input(
            id="my_input",
            value=DebounceState.value,
            on_change=DebounceState.set_value,
            debounce_timeout=250,
        )

    ctx, _page_ctx = _compile_single_page(page)

    assert len(ctx.memoize_wrappers) == 1, (
        "Expected the controlled rx.input to memoize as a single DebounceInput "
        f"wrapper, got: {list(ctx.memoize_wrappers)}"
    )
    wrapper_tag = next(iter(ctx.memoize_wrappers))
    assert "debounceinput" in wrapper_tag.lower(), (
        f"Memo wrapper tag should be derived from DebounceInput, got: {wrapper_tag!r}"
    )

    memo_files, _memo_imports = compile_memo_components(
        components=(),
        experimental_memos=tuple(ctx.auto_memo_components.values()),
    )
    memo_code = next(
        code for path, code in memo_files if Path(path).name == f"{wrapper_tag}.jsx"
    )

    assert re.search(
        r'^import\s+DebounceInput\s+from\s+"react-debounce-input"',
        memo_code,
        flags=re.MULTILINE,
    ), (
        "Memo body must import DebounceInput from react-debounce-input.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert "jsx(DebounceInput," in memo_code, (
        "Memo body must render via DebounceInput, not inline the inner TextField.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert "debounceTimeout:250" in memo_code, (
        "Memo body must pass debounceTimeout as a DebounceInput prop.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
    assert "element:RadixThemesTextField.Root" in memo_code, (
        "Memo body must pass the radix TextField as DebounceInput's element prop.\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )

    css_block_match = re.search(
        r"css:\(\{([^}]*)\}\)",
        memo_code,
    )
    css_contents = css_block_match.group(1) if css_block_match else ""
    assert "debounceTimeout" not in css_contents, (
        "debounceTimeout leaked into the css block — it should only be a "
        "DebounceInput prop. Reflex routes unknown TextFieldRoot kwargs into "
        "style, and DebounceInput.create copies child.style verbatim, so the "
        "timeout ends up duplicated as a no-op CSS key.\n"
        f"css block: {css_contents!r}\n"
        f"Memo code snippet: {memo_code[:2000]}"
    )
