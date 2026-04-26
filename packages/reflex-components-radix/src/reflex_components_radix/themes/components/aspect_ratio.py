"""AspectRatio — wrapper enforcing a width:height ratio (Tailwind-styled)."""

from __future__ import annotations

from typing import Any

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn


class AspectRatio(elements.Div):
    """Displays content with a desired ratio."""

    tag = "div"

    ratio: Var[float | int] = field(doc="Width:height ratio (e.g. 16/9 = 1.78)")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an aspect-ratio wrapper.

        Args:
            *children: Content (typically an <img>).
            **props: ``ratio`` plus standard div props.

        Returns:
            The aspect-ratio component.
        """
        ratio = props.pop("ratio", 1)
        existing = props.pop("class_name", "")
        if isinstance(ratio, (int, float)):
            style = props.pop("style", {}) or {}
            props["style"] = {**style, "aspect-ratio": str(ratio)}
        else:
            props["ratio"] = ratio
        props["class_name"] = cn("relative w-full overflow-hidden", existing)
        return super().create(*children, **props)


aspect_ratio = AspectRatio.create
