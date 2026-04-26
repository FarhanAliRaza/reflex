"""HoverCard — wraps ``@radix-ui/react-hover-card`` with Tailwind styling."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import popover_content_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.base import (
    RadixPrimitiveComponent,
    RadixPrimitiveTriggerComponent,
)


class _HoverCardElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-hover-card components."""

    library = "@radix-ui/react-hover-card@1.1.15"


class HoverCardRoot(_HoverCardElement):
    """Root component for HoverCard."""

    tag = "Root"
    alias = "RadixPrimitiveHoverCardRoot"

    default_open: Var[bool] = field(doc="Initial open state")
    open: Var[bool] = field(doc="Controlled open state")
    open_delay: Var[int] = field(doc="Open delay (ms)")
    close_delay: Var[int] = field(doc="Close delay (ms)")
    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")


class HoverCardPortal(_HoverCardElement):
    """Portal for hover-card content."""

    tag = "Portal"
    alias = "RadixPrimitiveHoverCardPortal"

    force_mount: Var[bool] = field(doc="Force mount")


class HoverCardTrigger(_HoverCardElement, RadixPrimitiveTriggerComponent):
    """Wraps the link/button that opens the hover card."""

    tag = "Trigger"
    alias = "RadixPrimitiveHoverCardTrigger"

    _memoization_mode = MemoizationMode(recursive=False)


class HoverCardContent(elements.Div, _HoverCardElement):
    """Hover-card content panel — auto-wraps in Portal."""

    tag = "Content"
    alias = "RadixPrimitiveHoverCardContent"

    side: Var[Responsive[Literal["top", "right", "bottom", "left"]]] = field(doc="Side")
    side_offset: Var[int] = field(doc="Side offset")
    align: Var[Literal["start", "center", "end"]] = field(doc="Align")
    align_offset: Var[int] = field(doc="Align offset")
    avoid_collisions: Var[bool] = field(doc="Avoid collisions")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="Padding")
    sticky: Var[Literal["partial", "always"]] = field(doc="Sticky")
    hide_when_detached: Var[bool] = field(doc="Hide when detached")
    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size "1" - "3"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create hover-card content wrapped in Portal.

        Args:
            *children: Content body.
            **props: Standard content props.

        Returns:
            The content component (already inside a portal).
        """
        existing = props.pop("class_name", "")
        props.pop("size", None)
        props["class_name"] = cn(popover_content_classes(), existing)
        content = super().create(*children, **props)
        return HoverCardPortal.create(content)


class HoverCard(ComponentNamespace):
    """HoverCard components namespace."""

    root = __call__ = staticmethod(HoverCardRoot.create)
    trigger = staticmethod(HoverCardTrigger.create)
    content = staticmethod(HoverCardContent.create)


hover_card = HoverCard()
