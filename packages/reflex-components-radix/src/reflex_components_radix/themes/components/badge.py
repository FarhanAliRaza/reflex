"""Badge — rendered as a plain ``<span>`` with Tailwind utility classes.

Public API matches the original Radix Themes wrapper. Internally uses
Tailwind utilities referencing Radix's ``--accent-*`` CSS variables;
no dependency on ``@radix-ui/themes``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import badge_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralRadius


class Badge(elements.Span):
    """A stylized badge element."""

    tag = "span"

    variant: Var[Literal["solid", "soft", "surface", "outline"]] = field(
        doc="Visual variant"
    )

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc="Badge size")

    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")

    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    radius: Var[LiteralRadius] = field(doc="Override theme radius")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a badge with Tailwind classes from variant/size.

        Args:
            *children: Badge content.
            **props: Standard span props plus the variant/size/colour props above.

        Returns:
            The badge component.
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
        props["class_name"] = cn(badge_classes(**selections), existing)
        return super().create(*children, **props)


badge = Badge.create
