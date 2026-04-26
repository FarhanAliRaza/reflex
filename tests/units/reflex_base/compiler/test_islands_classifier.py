"""Unit tests for the islands auto-placement classifier.

Covers ``packages/reflex-base/src/reflex_base/compiler/islands_classifier.py``.
"""

from __future__ import annotations

from typing import ClassVar

from reflex_base.compiler.islands_classifier import (
    AstroIslandPlacement,
    classify_islands,
)
from reflex_base.components.component import Component, HydratedComponent
from reflex_base.components.island import island
from reflex_components_core.base.bare import Bare


def _bare(text: str = "x"):
    return Bare.create(text)


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
