"""Card — container with surface/classic/ghost variants, Tailwind-styled.

Public API matches the original ``@radix-ui/themes`` Card; rendered as
a plain ``<div>`` with Tailwind utilities.
"""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import card_classes
from reflex_components_radix._variants import cn


class Card(elements.Div):
    """Container that groups related content and actions."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child element merging props")
    size: Var[Responsive[Literal["1", "2", "3", "4", "5"]]] = field(doc='Card size: "1" - "5"')
    variant: Var[Literal["surface", "classic", "ghost"]] = field(doc='Variant: surface|classic|ghost')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a card with Tailwind classes from variant/size.

        Args:
            *children: Card content.
            **props: Variant/size props plus standard div props.

        Returns:
            The card component.
        """
        variant = props.pop("variant", None)
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(variant, str):
            selections["variant"] = variant
        elif variant is not None:
            props["variant"] = variant
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["class_name"] = cn(card_classes(**selections), existing)
        return super().create(*children, **props)


card = Card.create
