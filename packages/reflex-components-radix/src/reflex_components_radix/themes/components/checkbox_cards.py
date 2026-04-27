"""CheckboxCards — grid of card-shaped checkbox tiles, Tailwind-styled."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

_CHECKBOX_CARDS_UID = itertools.count(1)


def _walk_checkbox_inputs(
    node: Any, group_name: str, default_values: set[str]
) -> None:
    """Set ``name`` on each hidden <input> and pre-check those in ``default_values``."""
    if isinstance(node, CheckboxCardsItem):
        raw = getattr(node, "_card_raw_value", None)
        if raw is not None:
            for input_node in node.children or []:
                if getattr(input_node, "tag", None) == "input":
                    input_node.name = LiteralVar.create(group_name)
                    if raw in default_values:
                        input_node.default_checked = LiteralVar.create(True)
    for child in getattr(node, "children", []) or []:
        _walk_checkbox_inputs(child, group_name, default_values)


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
        default_value = props.pop("default_value", None)
        defaults: set[str] = set()
        if isinstance(default_value, (list, tuple)):
            defaults = {v for v in default_value if isinstance(v, str)}
        group_name = props.pop("name", None) or f"_cc{next(_CHECKBOX_CARDS_UID)}"
        existing = props.pop("class_name", "")
        parts = ["grid"]
        if isinstance(columns, str):
            parts.append(f"grid-cols-{columns}")
        if isinstance(gap, str):
            parts.append(f"gap-[var(--space-{gap})]")
        props["class_name"] = cn(" ".join(parts), existing)
        for child in children:
            _walk_checkbox_inputs(child, group_name, defaults)
        return super().create(*children, **props)


class CheckboxCardsItem(elements.Label):
    """A card-shaped checkbox item."""

    tag = "label"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a CheckboxCards item.

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
            type="checkbox",
            value=raw_value,
            class_name="sr-only",
        )
        instance = super().create(hidden_input, *children, **props)
        instance._card_raw_value = (
            raw_value if isinstance(raw_value, str) else None
        )
        return instance


class CheckboxCards(SimpleNamespace):
    """CheckboxCards components namespace."""

    root = staticmethod(CheckboxCardsRoot.create)
    item = staticmethod(CheckboxCardsItem.create)


checkbox_cards = CheckboxCards()
