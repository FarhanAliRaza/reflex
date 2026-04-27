"""Grid — declarative grid layout, Tailwind-styled."""

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
        doc='Flow: row|column|dense|row-dense|column-dense'
    )
    align: Var[Responsive[LiteralAlign]] = field(doc='Cross-axis alignment')
    justify: Var[Responsive[LiteralJustify]] = field(doc='Main-axis alignment')
    spacing: Var[Responsive[LiteralSpacing]] = field(doc='Gap "0" - "9"')
    spacing_x: Var[Responsive[LiteralSpacing]] = field(doc='Column gap "0" - "9"')
    spacing_y: Var[Responsive[LiteralSpacing]] = field(doc='Row gap "0" - "9"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a grid container.

        Args:
            *children: Grid children.
            **props: columns/rows/flow/align/justify/spacing props.

        Returns:
            The grid component.
        """
        existing = props.pop("class_name", "")
        parts = ["grid"]

        columns = props.pop("columns", None)
        if isinstance(columns, str):
            parts.append(f"grid-cols-{columns}")
        elif columns is not None:
            props["columns"] = columns

        rows = props.pop("rows", None)
        if isinstance(rows, str):
            parts.append(f"grid-rows-{rows}")
        elif rows is not None:
            props["rows"] = rows

        for key, mapping in (("flow", _FLOW), ("align", _ALIGN), ("justify", _JUSTIFY)):
            value = props.pop(key, None)
            if isinstance(value, str):
                parts.append(mapping[value])
            elif value is not None:
                props[key] = value

        spacing = props.pop("spacing", None)
        if isinstance(spacing, str):
            parts.append(f"gap-[var(--space-{spacing})]")
        elif spacing is not None:
            props["spacing"] = spacing

        spacing_x = props.pop("spacing_x", None)
        if isinstance(spacing_x, str):
            parts.append(f"gap-x-[var(--space-{spacing_x})]")
        elif spacing_x is not None:
            props["spacing_x"] = spacing_x

        spacing_y = props.pop("spacing_y", None)
        if isinstance(spacing_y, str):
            parts.append(f"gap-y-[var(--space-{spacing_y})]")
        elif spacing_y is not None:
            props["spacing_y"] = spacing_y

        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


grid = Grid.create
