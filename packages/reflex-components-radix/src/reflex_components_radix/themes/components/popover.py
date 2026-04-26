"""Popover — wraps ``@radix-ui/react-popover`` with Tailwind styling."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import popover_content_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.base import (
    RadixPrimitiveComponent,
    RadixPrimitiveTriggerComponent,
)


class _PopoverElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-popover components."""

    library = "@radix-ui/react-popover@1.1.15"


class PopoverRoot(_PopoverElement):
    """Root component for Popover."""

    tag = "Root"
    alias = "RadixPrimitivePopoverRoot"

    open: Var[bool] = field(doc="Controlled open state")
    modal: Var[bool] = field(doc="Modal mode")
    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")
    default_open: Var[bool] = field(doc="Initial open state")


class PopoverPortal(_PopoverElement):
    """Portal for popover content."""

    tag = "Portal"
    alias = "RadixPrimitivePopoverPortal"

    force_mount: Var[bool] = field(doc="Force mount")


class PopoverTrigger(_PopoverElement, RadixPrimitiveTriggerComponent):
    """Wraps the control that opens the popover."""

    tag = "Trigger"
    alias = "RadixPrimitivePopoverTrigger"

    _memoization_mode = MemoizationMode(recursive=False)


class PopoverContent(elements.Div, _PopoverElement):
    """Popover content panel — auto-wraps in Portal."""

    tag = "Content"
    alias = "RadixPrimitivePopoverContent"

    size: Var[Responsive[Literal["1", "2", "3", "4"]]] = field(doc='Size "1" - "4"')
    side: Var[Literal["top", "right", "bottom", "left"]] = field(doc="Preferred side")
    side_offset: Var[int] = field(doc="Side offset (px)")
    align: Var[Literal["start", "center", "end"]] = field(doc="Alignment")
    align_offset: Var[int] = field(doc="Align offset")
    avoid_collisions: Var[bool] = field(doc="Avoid collisions")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="Padding")
    sticky: Var[Literal["partial", "always"]] = field(doc="Sticky behavior")
    hide_when_detached: Var[bool] = field(doc="Hide when detached")

    on_open_auto_focus: EventHandler[no_args_event_spec] = field(doc="Open focus.")
    on_close_auto_focus: EventHandler[no_args_event_spec] = field(doc="Close focus.")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="Pointer down outside.")
    on_focus_outside: EventHandler[no_args_event_spec] = field(doc="Focus outside.")
    on_interact_outside: EventHandler[no_args_event_spec] = field(doc="Interact outside.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create popover content wrapped in Portal.

        Args:
            *children: Popover body.
            **props: Standard content props.

        Returns:
            The content component (already inside a portal).
        """
        existing = props.pop("class_name", "")
        props.pop("size", None)
        props["class_name"] = cn(popover_content_classes(), existing)
        content = super().create(*children, **props)
        return PopoverPortal.create(content)


class PopoverClose(_PopoverElement, RadixPrimitiveTriggerComponent):
    """Closes the popover."""

    tag = "Close"
    alias = "RadixPrimitivePopoverClose"


class Popover(ComponentNamespace):
    """Popover components namespace."""

    root = staticmethod(PopoverRoot.create)
    trigger = staticmethod(PopoverTrigger.create)
    content = staticmethod(PopoverContent.create)
    close = staticmethod(PopoverClose.create)


popover = Popover()
