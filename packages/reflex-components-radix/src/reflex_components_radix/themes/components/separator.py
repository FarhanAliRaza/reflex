"""Separator — Tailwind-styled <hr>/horizontal divider."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import separator_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

LiteralSeparatorSize = Literal["1", "2", "3", "4"]


class Separator(elements.Div):
    """Visually or semantically separates content."""

    tag = "div"

    size: Var[Responsive[LiteralSeparatorSize]] = field(
        default=LiteralVar.create("4"),
        doc='Separator size: "1" - "4"',
    )
    color_scheme: Var[LiteralAccentColor] = field(doc="Separator color")
    orientation: Var[Responsive[Literal["horizontal", "vertical"]]] = field(
        doc="The orientation of the separator."
    )
    decorative: Var[bool] = field(doc="If true, separator is decorative-only.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a separator element.

        Args:
            *children: Ignored (separator is empty).
            **props: orientation/size and standard div props.

        Returns:
            The separator component.
        """
        orientation = props.pop("orientation", None)
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(orientation, str):
            selections["orientation"] = orientation
        elif orientation is not None:
            props["orientation"] = orientation
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props.setdefault("role", "separator")
        props["class_name"] = cn(separator_classes(**selections), existing)
        return super().create(**props)


divider = separator = Separator.create
