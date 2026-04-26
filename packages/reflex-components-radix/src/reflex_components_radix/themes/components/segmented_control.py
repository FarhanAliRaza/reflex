"""SegmentedControl — button-group toggle, Tailwind-styled.

Without ``@radix-ui/themes`` we render the Root as a flex container of
buttons; the active item gets a tinted background. Apps that need the
controlled / multi-select behaviour bind ``on_change`` per item.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import segmented_control_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


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
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props.setdefault("role", "tablist")
        props["class_name"] = cn(segmented_control_classes(**selections), existing)
        return super().create(*children, **props)


class SegmentedControlItem(elements.Button):
    """An item in the SegmentedControl."""

    tag = "button"

    value: Var[str] = field(doc="The value of the item.")

    _valid_parents: ClassVar[list[str]] = ["SegmentedControlRoot"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a SegmentedControl item.

        Args:
            *children: Item label.
            **props: ``value`` plus standard button props.

        Returns:
            The item component.
        """
        existing = props.pop("class_name", "")
        props.setdefault("type", "button")
        props.setdefault("role", "tab")
        props["class_name"] = cn(
            "flex-1 inline-flex items-center justify-center px-3 py-1 "
            "rounded-(--radius-2) text-[var(--gray-12)] cursor-pointer "
            "hover:bg-[var(--gray-a3)] "
            "data-[state=active]:bg-[var(--color-panel-solid)] "
            "data-[state=active]:shadow-sm "
            "transition-colors",
            existing,
        )
        return super().create(*children, **props)


class SegmentedControl(SimpleNamespace):
    """SegmentedControl components namespace."""

    root = staticmethod(SegmentedControlRoot.create)
    item = staticmethod(SegmentedControlItem.create)


segmented_control = SegmentedControl()
