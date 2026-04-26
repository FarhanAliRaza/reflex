"""Heading — Tailwind-styled heading element.

Public API matches the original Radix Themes ``Heading``. Renders as
a plain ``<h1>`` (or whatever ``as_`` specifies) with Tailwind classes
referencing Radix's CSS variables.
"""

from __future__ import annotations

from typing import Any, ClassVar

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.markdown_component_map import MarkdownComponentMap
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import heading_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

from .base import LiteralTextAlign, LiteralTextSize, LiteralTextTrim, LiteralTextWeight


class Heading(elements.H1, MarkdownComponentMap):
    """A foundational heading primitive based on the <h1>...<h6> elements."""

    tag = "h1"

    as_child: Var[bool] = field(doc="Render as child element merging props")
    as_: Var[str] = field(doc="Override semantic element (h1..h6, span, etc.)")

    size: Var[Responsive[LiteralTextSize]] = field(doc='Text size: "1" - "9"')
    weight: Var[Responsive[LiteralTextWeight]] = field(doc='Thickness: light|regular|medium|bold')
    align: Var[Responsive[LiteralTextAlign]] = field(doc='Alignment: left|center|right')
    trim: Var[Responsive[LiteralTextTrim]] = field(doc='Trim: normal|start|end|both')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a heading with Tailwind classes from size/weight/align.

        Args:
            *children: Heading content.
            **props: Standard heading props.

        Returns:
            The heading component.
        """
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        for key in ("size", "weight", "align"):
            value = props.pop(key, None)
            if isinstance(value, str):
                selections[key] = value
            elif value is not None:
                props[key] = value
        props["class_name"] = cn(heading_classes(**selections), existing)
        return super().create(*children, **props)


heading = Heading.create
