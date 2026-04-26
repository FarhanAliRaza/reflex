"""DropdownMenu — wraps ``@radix-ui/react-dropdown-menu`` with Tailwind styling."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import popover_content_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.base import (
    RadixPrimitiveComponent,
    RadixPrimitiveTriggerComponent,
)
from reflex_components_radix.themes.base import LiteralAccentColor

LiteralDirType = Literal["ltr", "rtl"]
LiteralSizeType = Literal["1", "2"]
LiteralVariantType = Literal["solid", "soft"]
LiteralSideType = Literal["top", "right", "bottom", "left"]
LiteralAlignType = Literal["start", "center", "end"]
LiteralStickyType = Literal["partial", "always"]


_item_classes = (
    "relative flex cursor-pointer select-none items-center "
    "rounded-(--radius-2) px-2 py-1.5 text-sm outline-none "
    "focus:bg-[var(--accent-3)] focus:text-[var(--accent-12)] "
    "data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
)
_separator_classes = "my-1 h-px bg-[var(--gray-a5)]"


class _DropdownMenuElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-dropdown-menu components."""

    library = "@radix-ui/react-dropdown-menu@2.1.15"


class DropdownMenuRoot(_DropdownMenuElement):
    """Root component for DropdownMenu."""

    tag = "Root"
    alias = "RadixPrimitiveDropdownMenuRoot"

    default_open: Var[bool] = field(doc="Initial open state")
    open: Var[bool] = field(doc="Controlled open state")
    modal: Var[bool] = field(doc="Modal mode")
    dir: Var[LiteralDirType] = field(doc="Reading direction")

    _invalid_children: ClassVar[list[str]] = ["DropdownMenuItem"]

    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")


class DropdownMenuTrigger(_DropdownMenuElement, RadixPrimitiveTriggerComponent):
    """Trigger that opens the menu."""

    tag = "Trigger"
    alias = "RadixPrimitiveDropdownMenuTrigger"

    _valid_parents: ClassVar[list[str]] = ["DropdownMenuRoot"]
    _invalid_children: ClassVar[list[str]] = ["DropdownMenuContent"]
    _memoization_mode = MemoizationMode(recursive=False)


class DropdownMenuPortal(_DropdownMenuElement):
    """Portal for menu content."""

    tag = "Portal"
    alias = "RadixPrimitiveDropdownMenuPortal"

    force_mount: Var[bool] = field(doc="Force mount")


class DropdownMenuContent(elements.Div, _DropdownMenuElement):
    """Menu content panel — auto-wraps in Portal."""

    tag = "Content"
    alias = "RadixPrimitiveDropdownMenuContent"

    size: Var[Responsive[LiteralSizeType]] = field(doc='Size "1" - "2"')
    variant: Var[LiteralVariantType] = field(doc="Variant: solid|soft")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    loop: Var[bool] = field(doc="Loop keyboard nav")
    force_mount: Var[bool] = field(doc="Force mount")
    side: Var[LiteralSideType] = field(doc="Side")
    side_offset: Var[float | int] = field(doc="Side offset")
    align: Var[LiteralAlignType] = field(doc="Align")
    align_offset: Var[float | int] = field(doc="Align offset")
    avoid_collisions: Var[bool] = field(doc="Avoid collisions")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="Padding")
    sticky: Var[LiteralStickyType] = field(doc="Sticky")
    hide_when_detached: Var[bool] = field(doc="Hide when detached")

    on_close_auto_focus: EventHandler[no_args_event_spec] = field(doc="Close focus.")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="Pointer outside.")
    on_focus_outside: EventHandler[no_args_event_spec] = field(doc="Focus outside.")
    on_interact_outside: EventHandler[no_args_event_spec] = field(doc="Interact outside.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create dropdown-menu content wrapped in Portal.

        Args:
            *children: Menu items.
            **props: Standard content props.

        Returns:
            The content component.
        """
        existing = props.pop("class_name", "")
        props.pop("size", None)
        props["class_name"] = cn(
            popover_content_classes(),
            "min-w-[8rem] p-1",
            existing,
        )
        content = super().create(*children, **props)
        return DropdownMenuPortal.create(content)


class DropdownMenuSub(_DropdownMenuElement):
    """Submenu container."""

    tag = "Sub"
    alias = "RadixPrimitiveDropdownMenuSub"

    open: Var[bool] = field(doc="Controlled open state")
    default_open: Var[bool] = field(doc="Initial open state")

    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")


class DropdownMenuSubTrigger(_DropdownMenuElement, RadixPrimitiveTriggerComponent):
    """Trigger that opens a submenu."""

    tag = "SubTrigger"
    alias = "RadixPrimitiveDropdownMenuSubTrigger"

    disabled: Var[bool] = field(doc="Disable")
    text_value: Var[str] = field(doc="Typeahead text")

    _valid_parents: ClassVar[list[str]] = ["DropdownMenuContent", "DropdownMenuSub"]
    _memoization_mode = MemoizationMode(recursive=False)

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a sub-trigger.

        Args:
            *children: Trigger label.
            **props: Standard props.

        Returns:
            The sub-trigger component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_item_classes, "data-[state=open]:bg-[var(--accent-3)]", existing)
        return super().create(*children, **props)


class DropdownMenuSubContent(elements.Div, _DropdownMenuElement):
    """Submenu content panel."""

    tag = "SubContent"
    alias = "RadixPrimitiveDropdownMenuSubContent"

    loop: Var[bool] = field(doc="Loop keyboard nav")
    force_mount: Var[bool] = field(doc="Force mount")
    side_offset: Var[float | int] = field(doc="Side offset")
    align_offset: Var[float | int] = field(doc="Align offset")
    avoid_collisions: Var[bool] = field(doc="Avoid collisions")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="Padding")
    sticky: Var[LiteralStickyType] = field(doc="Sticky")
    hide_when_detached: Var[bool] = field(doc="Hide when detached")

    _valid_parents: ClassVar[list[str]] = ["DropdownMenuSub"]

    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="Pointer outside.")
    on_focus_outside: EventHandler[no_args_event_spec] = field(doc="Focus outside.")
    on_interact_outside: EventHandler[no_args_event_spec] = field(doc="Interact outside.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a submenu content panel.

        Args:
            *children: Submenu items.
            **props: Standard props.

        Returns:
            The sub-content component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            popover_content_classes(),
            "min-w-[8rem] p-1",
            existing,
        )
        return super().create(*children, **props)


class DropdownMenuItem(_DropdownMenuElement):
    """A menu item."""

    tag = "Item"
    alias = "RadixPrimitiveDropdownMenuItem"

    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    shortcut: Var[str] = field(doc="Right-aligned shortcut text")
    disabled: Var[bool] = field(doc="Disable")
    text_value: Var[str] = field(doc="Typeahead text")

    _valid_parents: ClassVar[list[str]] = [
        "DropdownMenuContent",
        "DropdownMenuSubContent",
    ]

    on_select: EventHandler[no_args_event_spec] = field(doc="Item selected.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a menu item.

        Args:
            *children: Item label.
            **props: shortcut/disabled/text_value + standard props.

        Returns:
            The item component.
        """
        shortcut = props.pop("shortcut", None)
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_item_classes, existing)
        if shortcut is not None:
            children = (
                *children,
                elements.Span.create(
                    shortcut,
                    class_name="ml-auto text-xs tracking-widest text-[var(--gray-10)]",
                ),
            )
        return super().create(*children, **props)


class DropdownMenuSeparator(_DropdownMenuElement):
    """Visual separator between items."""

    tag = "Separator"
    alias = "RadixPrimitiveDropdownMenuSeparator"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a separator.

        Args:
            *children: Ignored.
            **props: Standard props.

        Returns:
            The separator component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_separator_classes, existing)
        return super().create(**props)


class DropdownMenu(ComponentNamespace):
    """DropdownMenu components namespace."""

    root = staticmethod(DropdownMenuRoot.create)
    trigger = staticmethod(DropdownMenuTrigger.create)
    content = staticmethod(DropdownMenuContent.create)
    sub_trigger = staticmethod(DropdownMenuSubTrigger.create)
    sub = staticmethod(DropdownMenuSub.create)
    sub_content = staticmethod(DropdownMenuSubContent.create)
    item = staticmethod(DropdownMenuItem.create)
    separator = staticmethod(DropdownMenuSeparator.create)


menu = dropdown_menu = DropdownMenu()
