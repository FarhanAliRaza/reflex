"""Tabs — wraps ``@radix-ui/react-tabs`` with Tailwind styling."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import (
    tabs_list_classes,
    tabs_trigger_classes,
)
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.base import RadixPrimitiveComponent
from reflex_components_radix.themes.base import LiteralAccentColor


class _TabsElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-tabs components."""

    library = "@radix-ui/react-tabs@1.1.13"


class TabsRoot(elements.Div, _TabsElement):
    """Root component for Tabs."""

    tag = "Root"
    alias = "RadixPrimitiveTabsRoot"

    default_value: Var[str] = field(doc="Initial active tab")
    value: Var[str] = field(doc="Controlled active tab")
    orientation: Var[Literal["horizontal", "vertical"]] = field(doc="Orientation")
    dir: Var[Literal["ltr", "rtl"]] = field(doc="Reading direction")
    activation_mode: Var[Literal["automatic", "manual"]] = field(doc="Activation")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[passthrough_event_spec(str)] = field(doc="Active change.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a tabs root.

        Args:
            *children: TabsList + TabsContent children.
            **props: Standard props.

        Returns:
            The root component.
        """
        orientation = props.get("orientation", "horizontal")
        existing = props.pop("class_name", "")
        cls_str = (
            "flex flex-col"
            if (not isinstance(orientation, str) or orientation == "horizontal")
            else "flex flex-row gap-4"
        )
        props["class_name"] = cn(cls_str, existing)
        return super().create(*children, **props)


class TabsList(elements.Div, _TabsElement):
    """Container for the tab triggers."""

    tag = "List"
    alias = "RadixPrimitiveTabsList"

    size: Var[Responsive[Literal["1", "2"]]] = field(doc='Size: "1" | "2"')
    loop: Var[bool] = field(doc="Loop keyboard nav")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a tabs list.

        Args:
            *children: TabsTrigger children.
            **props: size + standard props.

        Returns:
            The list component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["class_name"] = cn(tabs_list_classes(**selections), existing)
        return super().create(*children, **props)


class TabsTrigger(elements.Button, _TabsElement):
    """A single tab trigger."""

    tag = "Trigger"
    alias = "RadixPrimitiveTabsTrigger"

    value: Var[str] = field(doc="Tab value (must be unique)")
    disabled: Var[bool] = field(doc="Disable")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")

    _valid_parents: ClassVar[list[str]] = ["TabsList"]
    _memoization_mode = MemoizationMode(recursive=False)

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a tabs trigger.

        Args:
            *children: Trigger label.
            **props: Standard props.

        Returns:
            The trigger component.
        """
        existing = props.pop("class_name", "")
        if "color_scheme" in props:
            custom_attrs = props.setdefault("custom_attrs", {})
            custom_attrs["data-accent-color"] = props.pop("color_scheme")
        props["class_name"] = cn(tabs_trigger_classes(), existing)
        return super().create(*children, **props)


class TabsContent(elements.Div, _TabsElement):
    """Content panel associated with a trigger."""

    tag = "Content"
    alias = "RadixPrimitiveTabsContent"

    value: Var[str] = field(doc="Tab value to match")
    force_mount: Var[bool] = field(doc="Force mount when not active")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a tabs content panel.

        Args:
            *children: Panel content.
            **props: ``value`` + standard props.

        Returns:
            The content component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "mt-3 outline-none focus-visible:ring-2 "
            "focus-visible:ring-[var(--accent-8)]",
            existing,
        )
        return super().create(*children, **props)


class Tabs(ComponentNamespace):
    """Set of content sections to be displayed one at a time."""

    root = __call__ = staticmethod(TabsRoot.create)
    list = staticmethod(TabsList.create)
    trigger = staticmethod(TabsTrigger.create)
    content = staticmethod(TabsContent.create)


tabs = Tabs()
