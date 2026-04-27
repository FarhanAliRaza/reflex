"""Flex — declarative flexbox layout, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, responsive_classes
from reflex_components_radix.themes.base import (
    LiteralAlign,
    LiteralJustify,
    LiteralSpacing,
)

LiteralFlexDirection = Literal["row", "column", "row-reverse", "column-reverse"]
LiteralFlexWrap = Literal["nowrap", "wrap", "wrap-reverse"]


_DIRECTION = {
    "row": "flex-row",
    "column": "flex-col",
    "row-reverse": "flex-row-reverse",
    "column-reverse": "flex-col-reverse",
}
_ALIGN = {
    "start": "items-start",
    "center": "items-center",
    "end": "items-end",
    "baseline": "items-baseline",
    "stretch": "items-stretch",
}
_JUSTIFY = {
    "start": "justify-start",
    "center": "justify-center",
    "end": "justify-end",
    "between": "justify-between",
}
_WRAP = {
    "nowrap": "flex-nowrap",
    "wrap": "flex-wrap",
    "wrap-reverse": "flex-wrap-reverse",
}
# CSS ``display`` -> Tailwind utility. ``none`` becomes ``hidden`` (Tailwind's
# alias). Layered on top of the baseline ``flex`` class so ``display="none"``
# at base / ``display="flex"`` at md+ still produces a working hidden-then-
# revealed pattern via the source-order specificity rules.
_DISPLAY = {
    "none": "hidden",
    "inline": "inline",
    "inline-block": "inline-block",
    "block": "block",
    "grid": "grid",
    "inline-grid": "inline-grid",
    "flex": "flex",
    "inline-flex": "inline-flex",
}


def _spacing_class(spacing: str) -> str:
    return f"gap-[var(--space-{spacing})]"


class Flex(elements.Div):
    """Component for creating flex layouts."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child")
    direction: Var[Responsive[LiteralFlexDirection]] = field(
        doc="Direction: row|column|row-reverse|column-reverse"
    )
    align: Var[Responsive[LiteralAlign]] = field(
        doc="Cross-axis alignment: start|center|end|baseline|stretch"
    )
    justify: Var[Responsive[LiteralJustify]] = field(
        doc="Main-axis alignment: start|center|end|between"
    )
    wrap: Var[Responsive[LiteralFlexWrap]] = field(doc="Wrap: nowrap|wrap|wrap-reverse")
    spacing: Var[Responsive[LiteralSpacing]] = field(doc='Gap: "0" - "9"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a flex container.

        Args:
            *children: Flex children.
            **props: direction/align/justify/wrap/spacing + standard div
                props. Each layout prop accepts either a single value
                (``direction="column"``) or a Reflex ``Breakpoints`` mapping
                (``direction={"base":"column","md":"row"}``).

        Returns:
            The flex component.
        """
        existing = props.pop("class_name", "")
        parts = ["flex"]

        for key, formatter in (
            ("direction", _DIRECTION.get),
            ("align", _ALIGN.get),
            ("justify", _JUSTIFY.get),
            ("wrap", _WRAP.get),
            ("spacing", _spacing_class),
            ("display", _DISPLAY.get),
        ):
            value = props.pop(key, None)
            cls_str = responsive_classes(value, formatter)
            if cls_str:
                parts.append(cls_str)
            elif value is not None and not isinstance(value, (str, dict)):
                props[key] = value

        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


flex = Flex.create
