"""SegmentedControl — button-group toggle, Tailwind-styled.

Each item is a ``<label>`` wrapping a hidden ``<input type="radio">`` plus
its caption. The ``has-[input:checked]:`` Tailwind selector tints the
matching label without any JS state controller.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import segmented_control_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

_SEGCTRL_UID = itertools.count(1)


def _walk_segctrl_inputs(
    node: Any, group_name: str, default_value: str | None
) -> None:
    """Set ``name`` on each hidden <input> and pre-check the matching item."""
    if isinstance(node, SegmentedControlItem):
        raw = getattr(node, "_segctrl_raw_value", None)
        if raw is not None:
            for input_node in node.children or []:
                if getattr(input_node, "tag", None) == "input":
                    input_node.name = LiteralVar.create(group_name)
                    if default_value is not None and raw == default_value:
                        input_node.default_checked = LiteralVar.create(True)
    for child in getattr(node, "children", []) or []:
        _walk_segctrl_inputs(child, group_name, default_value)


class SegmentedControlRoot(elements.Div):
    """Root element for a SegmentedControl."""

    tag = "div"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size: "1"|"2"|"3"')
    variant: Var[Literal["classic", "surface"]] = field(doc="Variant")
    type: Var[Literal["single", "multiple"]] = field(doc="single|multiple selection")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    radius: Var[Literal["none", "small", "medium", "large", "full"]] = field(doc="Radius")
    default_value: Var[str | Sequence[str]] = field(doc="Default value")
    value: Var[str | Sequence[str]] = field(doc="Controlled value")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[passthrough_event_spec(str)] = field(
        doc="Fired when the active item changes."
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a SegmentedControl root.

        Args:
            *children: SegmentedControlItem children.
            **props: variant/size/colour props.

        Returns:
            The root component.
        """
        size = props.pop("size", None)
        default_value = props.pop("default_value", None)
        literal_default: str | None = (
            default_value if isinstance(default_value, str) else None
        )
        group_name = props.pop("name", None) or f"_sc{next(_SEGCTRL_UID)}"
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props.setdefault("role", "tablist")
        props["class_name"] = cn(segmented_control_classes(**selections), existing)
        for child in children:
            _walk_segctrl_inputs(child, group_name, literal_default)
        return super().create(*children, **props)


class SegmentedControlItem(elements.Label):
    """An item in the SegmentedControl."""

    tag = "label"

    value: Var[str] = field(doc="The value of the item.")

    _valid_parents: ClassVar[list[str]] = ["SegmentedControlRoot"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a SegmentedControl item.

        Args:
            *children: Item label.
            **props: ``value`` plus standard label props.

        Returns:
            The item component.
        """
        raw_value = props.pop("value", None)
        existing = props.pop("class_name", "")
        props.setdefault("role", "tab")
        props["class_name"] = cn(
            "flex-1 inline-flex items-center justify-center px-3 py-1 "
            "rounded-(--radius-2) text-[var(--gray-12)] cursor-pointer "
            "select-none transition-colors hover:bg-[var(--gray-a3)] "
            "has-[input:checked]:bg-[var(--color-panel-solid)] "
            "has-[input:checked]:shadow-sm "
            "has-[input:checked]:text-[var(--gray-12)]",
            existing,
        )
        hidden_input = elements.Input.create(
            type="radio",
            value=raw_value,
            class_name="sr-only",
        )
        instance = super().create(hidden_input, *children, **props)
        instance._segctrl_raw_value = (
            raw_value if isinstance(raw_value, str) else None
        )
        return instance


class SegmentedControl(SimpleNamespace):
    """SegmentedControl components namespace."""

    root = staticmethod(SegmentedControlRoot.create)
    item = staticmethod(SegmentedControlItem.create)


segmented_control = SegmentedControl()
