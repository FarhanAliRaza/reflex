"""Flex — declarative flexbox layout, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
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


def _spacing_class(spacing: str) -> str:
    return f"gap-[var(--space-{spacing})]"


class Flex(elements.Div):
    """Component for creating flex layouts."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child")
    direction: Var[Responsive[LiteralFlexDirection]] = field(
        doc='Direction: row|column|row-reverse|column-reverse'
    )
    align: Var[Responsive[LiteralAlign]] = field(
        doc='Cross-axis alignment: start|center|end|baseline|stretch'
    )
    justify: Var[Responsive[LiteralJustify]] = field(
        doc='Main-axis alignment: start|center|end|between'
    )
    wrap: Var[Responsive[LiteralFlexWrap]] = field(doc='Wrap: nowrap|wrap|wrap-reverse')
    spacing: Var[Responsive[LiteralSpacing]] = field(doc='Gap: "0" - "9"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a flex container.

        Args:
            *children: Flex children.
            **props: direction/align/justify/wrap/spacing + standard div props.

        Returns:
            The flex component.
        """
        existing = props.pop("class_name", "")
        parts = ["flex"]
        for key, mapping in (
            ("direction", _DIRECTION),
            ("align", _ALIGN),
            ("justify", _JUSTIFY),
            ("wrap", _WRAP),
        ):
            value = props.pop(key, None)
            if isinstance(value, str):
                parts.append(mapping[value])
            elif value is not None:
                props[key] = value
        spacing = props.pop("spacing", None)
        if isinstance(spacing, str):
            parts.append(_spacing_class(spacing))
        elif spacing is not None:
            props["spacing"] = spacing
        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


flex = Flex.create
