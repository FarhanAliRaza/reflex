"""CheckboxCards — grid of card-shaped checkbox tiles, Tailwind-styled."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


class CheckboxCardsRoot(elements.Div):
    """Root for a CheckboxCards grid."""

    tag = "div"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size: "1"|"2"|"3"')
    variant: Var[Literal["classic", "surface"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    columns: Var[
        Responsive[str | Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"]]
    ] = field(doc="Column count")
    gap: Var[
        Responsive[str | Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"]]
    ] = field(doc="Gap between cards")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a CheckboxCards grid.

        Args:
            *children: CheckboxCardsItem children.
            **props: columns/gap + standard div props.

        Returns:
            The grid component.
        """
        columns = props.pop("columns", "2")
        gap = props.pop("gap", "2")
        existing = props.pop("class_name", "")
        parts = ["grid"]
        if isinstance(columns, str):
            parts.append(f"grid-cols-{columns}")
        if isinstance(gap, str):
            parts.append(f"gap-[var(--space-{gap})]")
        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


class CheckboxCardsItem(elements.Label):
    """A card-shaped checkbox item."""

    tag = "label"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a CheckboxCards item.

        Args:
            *children: Item content.
            **props: Standard label props.

        Returns:
            The label component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "flex items-start gap-2 rounded-(--radius-3) "
            "border border-[var(--gray-a6)] p-3 cursor-pointer "
            "hover:bg-[var(--gray-a2)] "
            "has-[input:checked]:border-[var(--accent-9)] "
            "has-[input:checked]:bg-[var(--accent-3)] "
            "transition-colors",
            existing,
        )
        return super().create(*children, **props)


class CheckboxCards(SimpleNamespace):
    """CheckboxCards components namespace."""

    root = staticmethod(CheckboxCardsRoot.create)
    item = staticmethod(CheckboxCardsItem.create)


checkbox_cards = CheckboxCards()
