"""IconButton — square button optimised for a single icon child."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.match import Match
from reflex_components_core.el import elements
from reflex_components_lucide import Icon

from reflex_components_radix._radix_classes import icon_button_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import (
    LiteralAccentColor,
    LiteralRadius,
    LiteralVariant,
)

LiteralButtonSize = Literal["1", "2", "3", "4"]

RADIX_TO_LUCIDE_SIZE = {"1": 12, "2": 16, "3": 20, "4": 24}


class IconButton(elements.Button):
    """A button designed specifically for usage with a single icon."""

    tag = "button"

    as_child: Var[bool] = field(doc="Render as child")
    size: Var[Responsive[LiteralButtonSize]] = field(doc='Button size "1" - "4"')
    variant: Var[LiteralVariant] = field(doc='Variant: solid|soft|surface|outline|ghost|classic')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")
    radius: Var[LiteralRadius] = field(doc="Override theme radius")
    loading: Var[bool] = field(doc="Show a spinner instead of children")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an IconButton.

        Args:
            *children: Single Icon child (or string -> auto-wrapped in Icon).
            **props: Standard button props.

        Returns:
            The icon-button component.

        Raises:
            ValueError: If no child is supplied.
        """
        if children:
            if isinstance(children[0], str):
                children = [Icon.create(children[0])]
        else:
            msg = "IconButton requires a child icon."
            raise ValueError(msg)

        size = props.pop("size", None)
        variant = props.pop("variant", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(variant, str):
            selections["variant"] = variant
        elif variant is not None:
            props["variant"] = variant
        if isinstance(size, str):
            selections["size"] = size
            children[0].size = RADIX_TO_LUCIDE_SIZE[size]  # pyright: ignore[reportAttributeAccessIssue]
        elif size is not None:
            size_map_var = Match.create(
                size,
                *list(RADIX_TO_LUCIDE_SIZE.items()),
                12,
            )
            if not isinstance(size_map_var, Var):
                msg = f"Match did not return a Var: {size_map_var}"
                raise ValueError(msg)
            children[0].size = size_map_var  # pyright: ignore[reportAttributeAccessIssue]
            props["size"] = size
        props["class_name"] = cn(icon_button_classes(**selections), existing)
        return super().create(*children, **props)


icon_button = IconButton.create
