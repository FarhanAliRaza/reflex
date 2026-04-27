"""Button — rendered as a plain ``<button>`` with Tailwind utility classes.

Public API matches the original Radix Themes wrapper (``variant``,
``size``, ``color_scheme``, ``high_contrast``, ``radius``,
``loading``) so existing call sites keep working unchanged. Internally
the class uses Tailwind utilities referencing Radix's ``--accent-*``
CSS variables; no dependency on ``@radix-ui/themes``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import button_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import (
    LiteralAccentColor,
    LiteralRadius,
    LiteralVariant,
)

LiteralButtonSize = Literal["1", "2", "3", "4"]


class Button(elements.Button):
    """Trigger an action or event, such as submitting a form or displaying a dialog."""

    tag = "button"

    # Public API preserved (was on RadixThemesComponent etc).
    as_child: Var[bool] = field(
        doc="Render as a child element merging props/behaviour."
    )

    size: Var[Responsive[LiteralButtonSize]] = field(doc='Button size "1" - "4"')

    variant: Var[LiteralVariant] = field(doc='Variant: solid|soft|surface|outline|ghost|classic')

    color_scheme: Var[LiteralAccentColor] = field(doc="Override theme accent color")

    high_contrast: Var[bool] = field(doc="Higher contrast against background")

    radius: Var[LiteralRadius] = field(doc="Override theme radius")

    loading: Var[bool] = field(doc="Show a spinner instead of children")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a button with Tailwind classes from variant/size.

        Args:
            *children: Button label / icon children.
            **props: Standard button props plus the variant/size/colour
                /radius props above.

        Returns:
            The button component.
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
        classes = button_classes(**selections)
        props["class_name"] = cn(classes, existing)
        return super().create(*children, **props)


button = Button.create
