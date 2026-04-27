"""Code — inline ``<code>`` element with Tailwind utility classes."""

from __future__ import annotations

from typing import Any, ClassVar

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.markdown_component_map import MarkdownComponentMap
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import code_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralVariant

from .base import LiteralTextSize, LiteralTextWeight


class Code(elements.Code, MarkdownComponentMap):
    """An inline code segment."""

    tag = "code"

    variant: Var[LiteralVariant] = field(doc='Variant: solid|soft|outline|ghost')
    size: Var[Responsive[LiteralTextSize]] = field(doc='Text size: "1" - "9"')
    weight: Var[Responsive[LiteralTextWeight]] = field(doc='Thickness: light|regular|medium|bold')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a code element with Tailwind classes.

        Args:
            *children: Code content.
            **props: Standard code props plus variant/size/weight.

        Returns:
            The code component.
        """
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        for key in ("variant", "size"):
            value = props.pop(key, None)
            if isinstance(value, str):
                selections[key] = value
            elif value is not None:
                props[key] = value
        props["class_name"] = cn(code_classes(**selections), existing)
        return super().create(*children, **props)


code = Code.create
