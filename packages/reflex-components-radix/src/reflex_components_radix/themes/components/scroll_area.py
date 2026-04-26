"""ScrollArea — native overflow:auto wrapper, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn

_SCROLLBARS = {
    "vertical": "overflow-y-auto overflow-x-hidden",
    "horizontal": "overflow-x-auto overflow-y-hidden",
    "both": "overflow-auto",
}


class ScrollArea(elements.Div):
    """Custom styled scrollable area."""

    tag = "div"

    scrollbars: Var[Literal["vertical", "horizontal", "both"]] = field(doc="Axis")
    type: Var[Literal["auto", "always", "scroll", "hover"]] = field(doc="Visibility")
    scroll_hide_delay: Var[int] = field(doc="Hide delay (ms)")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a scroll area.

        Args:
            *children: Scrollable content.
            **props: scrollbars + standard div props.

        Returns:
            The scroll-area component.
        """
        scrollbars = props.pop("scrollbars", "vertical")
        existing = props.pop("class_name", "")
        cls_str = (
            _SCROLLBARS.get(scrollbars, "overflow-auto")
            if isinstance(scrollbars, str)
            else "overflow-auto"
        )
        props["class_name"] = cn(cls_str, existing)
        return super().create(*children, **props)


scroll_area = ScrollArea.create
