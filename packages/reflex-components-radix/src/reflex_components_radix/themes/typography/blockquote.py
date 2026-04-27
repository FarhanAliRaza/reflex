"""Blockquote — Tailwind-styled <blockquote> element."""

from __future__ import annotations

from typing import Any, ClassVar

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import blockquote_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

from .base import LiteralTextSize, LiteralTextWeight


class Blockquote(elements.Blockquote):
    """A block level extended quotation."""

    tag = "blockquote"

    size: Var[Responsive[LiteralTextSize]] = field(doc='Text size: "1" - "9"')
    weight: Var[Responsive[LiteralTextWeight]] = field(doc='Thickness: light|regular|medium|bold')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a blockquote element.

        Args:
            *children: Quote content.
            **props: Standard blockquote props plus size/weight.

        Returns:
            The blockquote component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["class_name"] = cn(blockquote_classes(**selections), existing)
        return super().create(*children, **props)


blockquote = Blockquote.create
