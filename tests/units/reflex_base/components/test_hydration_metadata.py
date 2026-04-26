"""Unit tests for Component hydration metadata (Astro migration Master Task 7).

The base `Component` class now declares four `ClassVar` flags that the Astro
target consults when placing client islands:

- requires_hydration
- provides_hydrated_context
- client_only
- heavy_bundle_group

`HydratedComponent` is a convenience subclass parallel to `NoSSRComponent`
that flips `requires_hydration` to True for wrapper authors.
"""

from __future__ import annotations

from reflex_base.components.component import (
    Component,
    HydratedComponent,
    NoSSRComponent,
)


def test_component_default_metadata():
    """Component base defaults all hydration flags to safe-not-hydrated values."""
    assert Component.requires_hydration is False
    assert Component.provides_hydrated_context is False
    assert Component.client_only is False
    assert Component.heavy_bundle_group is None


def test_hydrated_component_flips_requires_hydration():
    """HydratedComponent is the convenience opt-in flag for wrapper authors."""
    assert HydratedComponent.requires_hydration is True
    # Other flags remain at their conservative defaults; opt-in is explicit.
    assert HydratedComponent.provides_hydrated_context is False
    assert HydratedComponent.client_only is False
    assert HydratedComponent.heavy_bundle_group is None


def test_no_ssr_component_does_not_force_hydration():
    """NoSSRComponent and HydratedComponent are independent axes.

    NoSSR targets the SSR bypass (browser-only libraries), while
    requires_hydration targets island placement on the Astro target.
    """
    assert NoSSRComponent.requires_hydration is False


def test_component_subclass_can_override_metadata():
    """Subclasses can override the hydration flags directly (audit-time)."""

    class MyHeavyChart(Component):
        requires_hydration = True
        provides_hydrated_context = True
        heavy_bundle_group = "charts"

    assert MyHeavyChart.requires_hydration is True
    assert MyHeavyChart.provides_hydrated_context is True
    assert MyHeavyChart.heavy_bundle_group == "charts"
    # Sibling default still on the base class
    assert Component.requires_hydration is False
