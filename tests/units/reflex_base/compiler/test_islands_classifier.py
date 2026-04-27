"""Unit tests for the islands auto-placement classifier.

Covers ``packages/reflex-base/src/reflex_base/compiler/islands_classifier.py``.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from reflex_base.compiler.islands_classifier import (
    AstroIslandPlacement,
    classify_islands,
)
from reflex_base.components.component import Component, HydratedComponent, field
from reflex_base.components.island import island
from reflex_base.vars import VarData
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.base.bare import Bare

from reflex.experimental.memo import create_passthrough_component_memo


class _Plain(Component):
    tag = "Plain"
    library = "plain-lib"

    label: Var[str] = field(default=LiteralVar.create(""))


def _bare(text: str = "x"):
    return Bare.create(text)


def _state_var() -> Var:
    """A var bound to Reflex state (var_data.state set)."""
    return LiteralVar.create("v")._replace(
        merge_var_data=VarData(state="TestState")
    )


def _import_only_var() -> Var:
    """A var carrying only a build-time import (no state)."""
    return LiteralVar.create("v")._replace(merge_var_data=VarData(hooks={}))


def _wrap_memo(comp: Component, *, tag: str = "MemoTag"):
    """Build an auto-memo wrapper around ``comp`` and tag it like the plugin.

    Mirrors what :class:`MemoizeStatefulPlugin._build_wrapper` does: creates
    a passthrough wrapper and stamps the source component reference so the
    classifier can introspect runtime-state-ness.
    """
    wrapper_factory, _definition = create_passthrough_component_memo(tag, comp)
    wrapper = wrapper_factory()
    object.__setattr__(wrapper, "_memoized_source", comp)
    return wrapper


def test_classify_islands_static_tree_returns_no_placements():
    """A purely static tree produces no islands."""
    root = _bare("hello")
    assert classify_islands(root) == []


def test_classify_islands_path_b_requires_hydration_class():
    """Path B: a class with requires_hydration becomes a client:load island."""

    class StatefulWidget(HydratedComponent):
        tag = "StatefulWidget"

    inst = StatefulWidget.create()
    placements = classify_islands(inst)
    assert len(placements) == 1
    assert placements[0].component_name == "StatefulWidget"
    assert placements[0].directive == "client:load"
    assert placements[0].reason == "requires-hydration"


def test_classify_islands_path_b_provides_hydrated_context():
    """provides_hydrated_context promotes an island to client:load."""

    class ProviderWidget(Component):
        tag = "ProviderWidget"
        provides_hydrated_context: ClassVar[bool] = True

    inst = ProviderWidget.create()
    placements = classify_islands(inst)
    assert len(placements) == 1
    assert placements[0].reason == "provides-hydrated-context"
    assert placements[0].directive == "client:load"


def test_classify_islands_path_b_client_only():
    """client_only=True forces a client:only directive."""

    class BrowserOnly(Component):
        tag = "BrowserOnly"
        client_only: ClassVar[bool] = True

    inst = BrowserOnly.create()
    placements = classify_islands(inst)
    assert len(placements) == 1
    assert placements[0].directive == "client:only"
    assert placements[0].client_only is True
    assert placements[0].reason == "client-only"


def test_classify_islands_explicit_island_wrapper_load():
    """rx.island() with default hydrate='load' becomes client:load."""
    inner = _bare("x")
    wrapped = island(inner)  # pyright: ignore[reportArgumentType]
    placements = classify_islands(wrapped)  # pyright: ignore[reportArgumentType]
    assert len(placements) == 1
    assert placements[0].reason == "explicit-island"
    assert placements[0].directive == "client:load"


def test_classify_islands_explicit_island_wrapper_idle_visible():
    """The hydrate strategy maps to the matching client:* directive."""
    for strategy, expected in [
        ("load", "client:load"),
        ("idle", "client:idle"),
        ("visible", "client:visible"),
    ]:
        wrapped = island(_bare("x"), hydrate=strategy)  # pyright: ignore[reportArgumentType]
        placements = classify_islands(wrapped)  # pyright: ignore[reportArgumentType]
        assert placements[0].directive == expected


def test_classify_islands_explicit_island_wrapper_media_query():
    """A media-mapping spec emits client:visible + the media field."""
    wrapped = island(_bare("x"), hydrate={"media": "(max-width: 768px)"})  # pyright: ignore[reportArgumentType]
    placements = classify_islands(wrapped)  # pyright: ignore[reportArgumentType]
    assert placements[0].directive == "client:visible"
    assert placements[0].media == "(max-width: 768px)"


def test_classify_islands_explicit_client_only_overrides_strategy():
    """client_only=True forces client:only regardless of hydrate."""
    wrapped = island(_bare("x"), hydrate="visible", client_only=True)  # pyright: ignore[reportArgumentType]
    placements = classify_islands(wrapped)  # pyright: ignore[reportArgumentType]
    assert placements[0].directive == "client:only"
    assert placements[0].client_only is True


def test_classify_islands_dedupes_repeated_component_names():
    """Two ProviderWidget components on one page get unique generated names."""

    class Widget(HydratedComponent):
        tag = "Widget"

    container = _bare("")
    container.children = [Widget.create(), Widget.create()]  # pyright: ignore[reportAttributeAccessIssue]
    placements = classify_islands(container)
    names = [p.component_name for p in placements]
    assert names == ["Widget", "Widget_2"]


def test_classify_islands_suppression_under_island_root():
    """Descendants of an island root do not produce additional islands."""

    class Outer(HydratedComponent):
        tag = "Outer"

    class Inner(HydratedComponent):
        tag = "Inner"

    outer = Outer.create()
    outer.children = [Inner.create()]  # pyright: ignore[reportAttributeAccessIssue]
    placements = classify_islands(outer)
    assert len(placements) == 1
    assert placements[0].component_name == "Outer"


def test_classify_islands_descends_into_static_parent_for_inner_state():
    """A static parent with a stateful child should yield only the child island."""

    class ChildWidget(HydratedComponent):
        tag = "ChildWidget"

    container = _bare("")
    container.children = [ChildWidget.create()]  # pyright: ignore[reportAttributeAccessIssue]
    placements = classify_islands(container)
    assert len(placements) == 1
    assert placements[0].component_name == "ChildWidget"


def test_classify_islands_explicit_island_inside_static_parent():
    """An rx.island() wrapped inside a static parent is still emitted."""

    class StaticBox(Component):
        tag = "StaticBox"

    inner = _bare("x")
    box = StaticBox.create()
    box.children = [island(inner)]  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
    placements = classify_islands(box)
    assert len(placements) == 1
    assert placements[0].reason == "explicit-island"


def test_classify_islands_to_astro_island_round_trips_directive():
    """AstroIslandPlacement.to_astro_island carries directive + media."""
    placement = AstroIslandPlacement(
        component_name="C",
        directive="client:visible",
        reason="tree-signal",
        media="(min-width: 1024px)",
    )
    out = placement.to_astro_island(module_path="../mod.tsx")
    assert out.component_name == "C"
    assert out.module_path == "../mod.tsx"
    assert out.directive == "client:visible"
    assert out.media == "(min-width: 1024px)"


def test_classify_islands_to_astro_island_rejects_ssr_only():
    """SSR-only placements have no client directive and cannot become AstroIslands.

    AstroIsland describes a hydrating client island; mapping an SSR-only
    placement onto it would silently default the directive and ship JS for
    a component that was deliberately classified as static.
    """
    placement = AstroIslandPlacement(
        component_name="C",
        directive=None,
        reason="ssr-only",
    )
    with pytest.raises(ValueError, match="ssr-only"):
        placement.to_astro_island(module_path="../mod.tsx")


def test_classify_islands_memo_wrapper_no_state_is_ssr_only():
    """A memo wrapper around a stateless component classifies as SSR-only.

    Auto-memoize fires on any var_data — including pure build-time signals
    such as icon imports — so the wrapper alone is not a reliable
    runtime-state marker. The classifier must inspect the wrapped source.
    """
    inner = _Plain.create()  # no state, no event triggers
    wrapper = _wrap_memo(inner, tag="StatelessMemo")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "ssr-only"
    assert placements[0].directive is None
    # The component name comes from the wrapper's tag (= export name in
    # the generated React module), not the dynamic Python class name.
    assert placements[0].component_name == "StatelessMemo"


def test_classify_islands_memo_wrapper_with_state_is_hydrating_island():
    """A memo wrapper whose source has a state-bound var hydrates."""
    inner = _Plain.create(label=_state_var())
    wrapper = _wrap_memo(inner, tag="StatefulMemo")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "tree-signal"
    assert placements[0].directive == "client:idle"
    assert placements[0].component_name == "StatefulMemo"


def test_classify_islands_memo_wrapper_with_event_trigger_hydrates():
    """A memo wrapper whose source has an event trigger hydrates.

    Event triggers always need a hydration root; their callbacks run
    client-side regardless of any state binding on the props.
    """
    inner = _Plain.create()
    inner.event_triggers["on_click"] = LiteralVar.create("noop")
    wrapper = _wrap_memo(inner, tag="ClickableMemo")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "tree-signal"
    assert placements[0].directive == "client:idle"


def test_classify_islands_memo_wrapper_descendant_state_hydrates():
    """A memo wrapper hydrates when any descendant carries runtime state.

    The classifier walks through the wrapped subtree (including nested
    memo wrappers) so an outer memo containing a stateful inner memo
    correctly propagates the hydration need outward.
    """
    stateful_leaf = _Plain.create(label=_state_var())
    parent = _Plain.create()
    parent.children = [stateful_leaf]
    wrapper = _wrap_memo(parent, tag="OuterMemo")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "tree-signal"
    assert placements[0].directive == "client:idle"


def test_classify_islands_memo_wrapper_import_only_var_is_ssr_only():
    """A memo wrapper whose source's only var_data is an import is SSR-only.

    Mirrors the icon component pattern: a prop carries a build-time
    import directive (no state, no hooks), which triggers auto-memoize
    but produces zero runtime behavior. Hydrating it would ship and
    register an unused React root per icon.
    """
    inner = _Plain.create(label=_import_only_var())
    wrapper = _wrap_memo(inner, tag="IconLikeMemo")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "ssr-only"
    assert placements[0].directive is None


def test_classify_islands_memo_without_source_falls_back_to_hydration():
    """A memo wrapper missing ``_memoized_source`` is conservatively hydrated.

    Older codepaths (or future producers) may construct a wrapper without
    stamping the source reference. Without visibility into the subtree,
    the classifier must err on the side of hydrating.
    """
    inner = _Plain.create()
    wrapper_factory, _definition = create_passthrough_component_memo(
        "OrphanMemo", inner
    )
    wrapper = wrapper_factory()
    # Deliberately do NOT set _memoized_source.
    assert not hasattr(wrapper, "_memoized_source")
    placements = classify_islands(wrapper)
    assert len(placements) == 1
    assert placements[0].reason == "tree-signal"
    assert placements[0].directive == "client:idle"


def test_classify_islands_ssr_only_descends_into_children():
    """SSR-only placements still allow nested islands underneath.

    Unlike a hydrating island (which subsumes its subtree under one
    React root), an SSR-only memo wrapper renders to static HTML. Any
    state-bearing descendants still need their own hydration islands.
    """

    class StatefulChild(HydratedComponent):
        tag = "StatefulChild"

    inert_parent = _Plain.create()
    wrapper = _wrap_memo(inert_parent, tag="InertParent")
    # Inject a stateful descendant under the wrapper.
    wrapper.children = [StatefulChild.create()]  # pyright: ignore[reportAttributeAccessIssue]
    placements = classify_islands(wrapper)
    reasons = [p.reason for p in placements]
    names = [p.component_name for p in placements]
    assert "ssr-only" in reasons
    assert "requires-hydration" in reasons
    assert "InertParent" in names
    assert "StatefulChild" in names
