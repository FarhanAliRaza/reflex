"""RadioCards — grid of card-shaped radio tiles, Tailwind-styled."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


class RadioCardsRoot(elements.Div):
    """Root for a RadioCards grid."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child")
    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc="Size")
    variant: Var[Literal["classic", "surface"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    columns: Var[
        Responsive[str | Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"]]
    ] = field(doc="Column count")
    gap: Var[
        Responsive[str | Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"]]
    ] = field(doc="Gap between cards")
    default_value: Var[str] = field(doc="Default value")
    value: Var[str] = field(doc="Controlled value")
    name: Var[str] = field(doc="Form name")
    disabled: Var[bool] = field(doc="Disable")
    required: Var[bool] = field(doc="Required")
    orientation: Var[Literal["horizontal", "vertical", "undefined"]] = field(doc="Orientation")
    dir: Var[Literal["ltr", "rtl"]] = field(doc="Direction")
    loop: Var[bool] = field(doc="Loop keyboard nav")

    on_value_change: EventHandler[passthrough_event_spec(str)] = field(
        doc="Fired when the selected value changes."
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a RadioCards grid.

        Args:
            *children: RadioCardsItem children.
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
        props.setdefault("role", "radiogroup")
        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


class RadioCardsItem(elements.Label):
    """A card-shaped radio item."""

    tag = "label"

    as_child: Var[bool] = field(doc="Render as child")
    value: Var[str] = field(doc="Item value")
    disabled: Var[bool] = field(doc="Disable")
    required: Var[bool] = field(doc="Required")

    _valid_parents: ClassVar[list[str]] = ["RadioCardsRoot"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a RadioCards item.

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


class RadioCards(SimpleNamespace):
    """RadioCards components namespace."""

    root = staticmethod(RadioCardsRoot.create)
    item = staticmethod(RadioCardsItem.create)


radio_cards = RadioCards()
