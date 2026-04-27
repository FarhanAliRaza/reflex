"""Grid — declarative grid layout, Tailwind-styled."""

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

LiteralGridFlow = Literal["row", "column", "dense", "row-dense", "column-dense"]


_FLOW = {
    "row": "grid-flow-row",
    "column": "grid-flow-col",
    "dense": "grid-flow-dense",
    "row-dense": "grid-flow-row-dense",
    "column-dense": "grid-flow-col-dense",
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


class Grid(elements.Div):
    """Component for creating grid layouts."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child")
    columns: Var[Responsive[str]] = field(doc="Number of columns")
    rows: Var[Responsive[str]] = field(doc="Number of rows")
    flow: Var[Responsive[LiteralGridFlow]] = field(
        doc="Flow: row|column|dense|row-dense|column-dense"
    )
    align: Var[Responsive[LiteralAlign]] = field(doc="Cross-axis alignment")
    justify: Var[Responsive[LiteralJustify]] = field(doc="Main-axis alignment")
    spacing: Var[Responsive[LiteralSpacing]] = field(doc='Gap "0" - "9"')
    spacing_x: Var[Responsive[LiteralSpacing]] = field(doc='Column gap "0" - "9"')
    spacing_y: Var[Responsive[LiteralSpacing]] = field(doc='Row gap "0" - "9"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a grid container.

        Args:
            *children: Grid children.
            **props: columns/rows/flow/align/justify/spacing props. Each
                accepts either a single value (``columns="3"``) or a
                Reflex ``Breakpoints`` mapping
                (``columns={"base":"1","sm":"2","lg":"3"}``).

        Returns:
            The grid component.
        """
        existing = props.pop("class_name", "")
        parts = ["grid"]

        for key, formatter in (
            ("columns", lambda v: f"grid-cols-{v}"),
            ("rows", lambda v: f"grid-rows-{v}"),
            ("flow", _FLOW.get),
            ("align", _ALIGN.get),
            ("justify", _JUSTIFY.get),
            ("spacing", lambda v: f"gap-[var(--space-{v})]"),
            ("spacing_x", lambda v: f"gap-x-[var(--space-{v})]"),
            ("spacing_y", lambda v: f"gap-y-[var(--space-{v})]"),
        ):
            value = props.pop(key, None)
            cls_str = responsive_classes(value, formatter)
            if cls_str:
                parts.append(cls_str)
            elif value is not None and not isinstance(value, (str, dict)):
                props[key] = value

        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


grid = Grid.create
