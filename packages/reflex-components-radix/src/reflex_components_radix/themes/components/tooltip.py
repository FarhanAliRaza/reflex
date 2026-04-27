"""Tooltip — CSS-only group-hover popup styled with Tailwind utilities.

The original Radix Themes Tooltip used a portal + JS positioning. This
rewrite renders the trigger inline and an absolutely-positioned bubble
sibling that becomes visible on hover/focus via Tailwind's ``group``
modifier. No JS, no portal, no @radix-ui/react-tooltip dependency. The
trade-off vs the JS-driven version: no collision detection, no delayed
open. Apps needing those should compose dropdown_menu instead.
"""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.utils import format
from reflex_base.vars.base import Var
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn

LiteralSideType = Literal["top", "right", "bottom", "left"]
LiteralAlignType = Literal["start", "center", "end"]
LiteralStickyType = Literal["partial", "always"]

ARIA_LABEL_KEY = "aria_label"


_SIDE_POSITION = {
    "top": "bottom-full left-1/2 -translate-x-1/2 mb-2",
    "bottom": "top-full left-1/2 -translate-x-1/2 mt-2",
    "left": "right-full top-1/2 -translate-y-1/2 mr-2",
    "right": "left-full top-1/2 -translate-y-1/2 ml-2",
}


class Tooltip(elements.Span):
    """A hover/focus tooltip wrapping a trigger child."""

    tag = "span"

    content: Var[str] = field(doc="The content of the tooltip.")
    default_open: Var[bool] = field(doc="(no-op)")
    open: Var[bool] = field(doc="(no-op)")
    side: Var[LiteralSideType] = field(doc="Preferred side (default top)")
    side_offset: Var[float | int] = field(doc="(no-op)")
    align: Var[LiteralAlignType] = field(doc="(no-op)")
    align_offset: Var[float | int] = field(doc="(no-op)")
    avoid_collisions: Var[bool] = field(doc="(no-op)")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="(no-op)")
    arrow_padding: Var[float | int] = field(doc="(no-op)")
    sticky: Var[LiteralStickyType] = field(doc="(no-op)")
    hide_when_detached: Var[bool] = field(doc="(no-op)")
    delay_duration: Var[float | int] = field(doc="(no-op)")
    disable_hoverable_content: Var[bool] = field(doc="(no-op)")
    force_mount: Var[bool] = field(doc="(no-op)")
    aria_label: Var[str] = field(doc="ARIA label override")

    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="(no-op)")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="(no-op)")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="(no-op)")

    _memoization_mode = MemoizationMode(recursive=False)

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a tooltip wrapper.

        Args:
            *children: The trigger child.
            **props: ``content`` plus side/align props.

        Returns:
            The tooltip component (a span containing the trigger and a
            popover bubble that's visible on hover/focus).
        """
        if props.get(ARIA_LABEL_KEY) is not None:
            props[format.to_kebab_case(ARIA_LABEL_KEY)] = props.pop(ARIA_LABEL_KEY)

        content = props.pop("content", "")
        side = props.pop("side", "top")
        existing = props.pop("class_name", "")
        side_str = side if isinstance(side, str) else "top"
        bubble = elements.Span.create(
            content,
            class_name=(
                "absolute z-50 hidden group-hover:block group-focus-within:block "
                "rounded-(--radius-2) bg-[var(--gray-12)] px-2 py-1 text-xs "
                f"text-[var(--gray-1)] shadow-md whitespace-nowrap "
                f"{_SIDE_POSITION.get(side_str, _SIDE_POSITION['top'])}"
            ),
            role="tooltip",
        )
        props["class_name"] = cn("relative inline-flex group", existing)
        return super().create(*children, bubble, **props)


tooltip = Tooltip.create
