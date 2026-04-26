"""Unit tests for the static-mode classifier and rejection helper.

Covers ``packages/reflex-base/src/reflex_base/compiler/static_mode.py``.
"""

from __future__ import annotations

import pytest
from reflex_base.compiler.static_mode import (
    StaticModeViolation,
    find_static_mode_violations,
    reject_static_mode_violations,
)
from reflex_base.components.component import (
    Component,
    HydratedComponent,
    NoSSRComponent,
)
from reflex_base.components.island import island
from reflex_base.utils.exceptions import CompileError
from reflex_components_core.base.bare import Bare


def _bare(text: str) -> Component:
    """Build a stateless ``Bare`` component containing literal text.

    Args:
        text: The literal contents.

    Returns:
        A ``Bare`` component wrapping the literal text.
    """
    return Bare.create(text)


def test_static_safe_tree_returns_no_violations():
    """Plain literals + no triggers + no metadata = no violations."""
    root = _bare("hello")
    assert find_static_mode_violations(route="/", root=root) == []


def test_event_trigger_is_violation():
    """A component with an event trigger fails static mode."""

    def _on_click():
        return []

    root = Bare.create("click me")
    # Inject a synthetic event trigger.
    root.event_triggers["on_click"] = _on_click  # pyright: ignore[reportArgumentType]
    violations = find_static_mode_violations(route="/", root=root)
    assert len(violations) == 1
    assert "event triggers" in violations[0].reason
    assert "on_click" in (violations[0].detail or "")


def test_island_wrapper_is_violation():
    """rx.island(...) on a static page is rejected."""
    inner = _bare("x")
    wrapped = island(inner)  # pyright: ignore[reportArgumentType]
    violations = find_static_mode_violations(route="/", root=wrapped)  # pyright: ignore[reportArgumentType]
    # The wrapper itself is reported once, and we don't double-report the inner
    # if it's safe.
    assert any("rx.island" in v.reason for v in violations)


def test_hydrated_component_is_violation():
    """A subclass that declares requires_hydration fails static mode."""

    class StatefulWidget(HydratedComponent):
        tag = "StatefulWidget"

    inst = StatefulWidget.create()
    violations = find_static_mode_violations(route="/", root=inst)
    assert len(violations) == 1
    assert "hydration metadata" in violations[0].reason


def test_client_only_component_is_violation():
    """A class flagged client_only=True fails static mode."""

    class BrowserOnly(Component):
        tag = "BrowserOnly"
        client_only = True

    inst = BrowserOnly.create()
    violations = find_static_mode_violations(route="/", root=inst)
    assert len(violations) == 1
    assert "hydration metadata" in violations[0].reason


def test_no_ssr_component_alone_is_not_violation():
    """NoSSRComponent without requires_hydration is a render concern only.

    Static mode rejects on hydration flags, not on SSR exemption — those are
    independent axes per Master Task 7.
    """

    class JustNoSSR(NoSSRComponent):
        tag = "JustNoSSR"

    inst = JustNoSSR.create()
    violations = find_static_mode_violations(route="/", root=inst)
    assert violations == []


def test_reject_static_mode_violations_no_op_when_clean():
    """When there are no violations, the helper returns silently."""
    root = _bare("hello")
    reject_static_mode_violations(route="/", root=root)


def test_reject_static_mode_violations_raises_with_named_offender():
    """When a violation exists, the CompileError lists the offender."""

    class StatefulWidget(HydratedComponent):
        tag = "StatefulWidget"

    inst = StatefulWidget.create()
    with pytest.raises(CompileError) as excinfo:
        reject_static_mode_violations(route="/landing", root=inst)
    msg = str(excinfo.value)
    assert "/landing" in msg
    assert "StatefulWidget" in msg
    assert "render_mode='static'" in msg
    assert "render_mode='app'" in msg or "render_mode='islands'" in msg


def test_reject_static_mode_violations_lists_multiple():
    """Multiple violations are all reported in one error."""

    class StatefulA(HydratedComponent):
        tag = "StatefulA"

    class StatefulB(HydratedComponent):
        tag = "StatefulB"

    a = StatefulA.create()
    b = StatefulB.create()
    container = Bare.create("")
    container.children = [a, b]  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(CompileError) as excinfo:
        reject_static_mode_violations(route="/x", root=container)
    msg = str(excinfo.value)
    assert "StatefulA" in msg
    assert "StatefulB" in msg


def test_static_mode_violation_format_includes_detail():
    """Detail strings appear inline with the offender name."""
    v = StaticModeViolation(
        route="/x",
        component_name="Foo",
        reason="event triggers are not allowed on static pages",
        detail="triggers=on_click",
    )
    formatted = v.format()
    assert "/x" in formatted
    assert "Foo" in formatted
    assert "on_click" in formatted
