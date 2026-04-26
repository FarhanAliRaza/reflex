"""Radio — single native ``<input type=radio>`` styled with Tailwind."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import radio_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


class Radio(elements.Input):
    """A standalone radio control."""

    tag = "input"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size: "1"|"2"|"3"')
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    as_child: Var[bool] = field(doc="Render as child")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a single radio.

        Args:
            *children: Ignored.
            **props: Standard radio props.

        Returns:
            The radio component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["type"] = "radio"
        props["class_name"] = cn(
            radio_classes(**selections), "appearance-none", existing,
        )
        return super().create(**props)


radio = Radio.create
