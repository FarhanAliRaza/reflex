"""RadioCards — grid of card-shaped radio tiles, Tailwind-styled."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

_RADIO_CARDS_UID = itertools.count(1)


def _walk_card_inputs(node: Any, group_name: str, default_value: str | None) -> None:
    """Set ``name`` on every hidden <input> under a RadioCards label and pre-check."""
    if isinstance(node, RadioCardsItem):
        raw = getattr(node, "_card_raw_value", None)
        if raw is not None:
            for input_node in node.children or []:
                if getattr(input_node, "tag", None) == "input":
                    input_node.name = LiteralVar.create(group_name)
                    if default_value is not None and raw == default_value:
                        input_node.default_checked = LiteralVar.create(True)
    for child in getattr(node, "children", []) or []:
        _walk_card_inputs(child, group_name, default_value)


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
        default_value = props.pop("default_value", None)
        literal_default: str | None = (
            default_value if isinstance(default_value, str) else None
        )
        group_name = props.pop("name", None) or f"_rc{next(_RADIO_CARDS_UID)}"
        existing = props.pop("class_name", "")
        parts = ["grid"]
        if isinstance(columns, str):
            parts.append(f"grid-cols-{columns}")
        if isinstance(gap, str):
            parts.append(f"gap-[var(--space-{gap})]")
        props.setdefault("role", "radiogroup")
        props["class_name"] = cn(" ".join(parts), existing)
        for child in children:
            _walk_card_inputs(child, group_name, literal_default)
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
            **props: ``value`` + standard label props.

        Returns:
            The label component.
        """
        raw_value = props.pop("value", None)
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
        hidden_input = elements.Input.create(
            type="radio",
            value=raw_value,
            class_name="sr-only",
        )
        instance = super().create(hidden_input, *children, **props)
        instance._card_raw_value = (
            raw_value if isinstance(raw_value, str) else None
        )
        return instance


class RadioCards(SimpleNamespace):
    """RadioCards components namespace."""

    root = staticmethod(RadioCardsRoot.create)
    item = staticmethod(RadioCardsItem.create)


radio_cards = RadioCards()
