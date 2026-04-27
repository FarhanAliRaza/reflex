"""ContextMenu — wraps ``@radix-ui/react-context-menu`` with Tailwind styling."""

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
from reflex_components_radix.themes.base import LiteralAccentColor, apply_portal_theme

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


class _ContextMenuElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-context-menu components."""

    library = "@radix-ui/react-context-menu@2.2.15"


class ContextMenuRoot(_ContextMenuElement):
    """Root component for ContextMenu."""

    tag = "Root"
    alias = "RadixPrimitiveContextMenuRoot"

    modal: Var[bool] = field(doc="Modal mode")
    dir: Var[LiteralDirType] = field(doc="Reading direction")

    _invalid_children: ClassVar[list[str]] = ["ContextMenuItem"]

    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")


class ContextMenuTrigger(_ContextMenuElement, RadixPrimitiveTriggerComponent):
    """Wraps the element that opens the context menu."""

    tag = "Trigger"
    alias = "RadixPrimitiveContextMenuTrigger"

    disabled: Var[bool] = field(doc="Disable")

    _valid_parents: ClassVar[list[str]] = ["ContextMenuRoot"]
    _invalid_children: ClassVar[list[str]] = ["ContextMenuContent"]
    _memoization_mode = MemoizationMode(recursive=False)


class ContextMenuPortal(_ContextMenuElement):
    """Portal for context-menu content."""

    tag = "Portal"
    alias = "RadixPrimitiveContextMenuPortal"

    force_mount: Var[bool] = field(doc="Force mount")


class ContextMenuContent(elements.Div, _ContextMenuElement):
    """Context-menu content panel — auto-wraps in Portal."""

    tag = "Content"
    alias = "RadixPrimitiveContextMenuContent"

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
        """Create context-menu content wrapped in Portal.

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
        apply_portal_theme(props)
        content = super().create(*children, **props)
        return ContextMenuPortal.create(content)


class ContextMenuSub(_ContextMenuElement):
    """Submenu container."""

    tag = "Sub"
    alias = "RadixPrimitiveContextMenuSub"

    open: Var[bool] = field(doc="Controlled open state")
    default_open: Var[bool] = field(doc="Initial open state")

    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")


class ContextMenuSubTrigger(_ContextMenuElement, RadixPrimitiveTriggerComponent):
    """Trigger that opens a submenu."""

    tag = "SubTrigger"
    alias = "RadixPrimitiveContextMenuSubTrigger"

    disabled: Var[bool] = field(doc="Disable")
    text_value: Var[str] = field(doc="Typeahead text")

    _valid_parents: ClassVar[list[str]] = ["ContextMenuContent", "ContextMenuSub"]
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


class ContextMenuSubContent(elements.Div, _ContextMenuElement):
    """Submenu content panel."""

    tag = "SubContent"
    alias = "RadixPrimitiveContextMenuSubContent"

    loop: Var[bool] = field(doc="Loop keyboard nav")
    force_mount: Var[bool] = field(doc="Force mount")
    side_offset: Var[float | int] = field(doc="Side offset")
    align_offset: Var[float | int] = field(doc="Align offset")
    avoid_collisions: Var[bool] = field(doc="Avoid collisions")
    collision_padding: Var[float | int | dict[str, float | int]] = field(doc="Padding")
    sticky: Var[LiteralStickyType] = field(doc="Sticky")
    hide_when_detached: Var[bool] = field(doc="Hide when detached")

    _valid_parents: ClassVar[list[str]] = ["ContextMenuSub"]

    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="Pointer outside.")
    on_focus_outside: EventHandler[no_args_event_spec] = field(doc="Focus outside.")
    on_interact_outside: EventHandler[no_args_event_spec] = field(doc="Interact outside.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create submenu content.

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
        apply_portal_theme(props)
        return super().create(*children, **props)


class ContextMenuItem(_ContextMenuElement):
    """A menu item."""

    tag = "Item"
    alias = "RadixPrimitiveContextMenuItem"

    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    shortcut: Var[str] = field(doc="Right-aligned shortcut text")
    disabled: Var[bool] = field(doc="Disable")
    text_value: Var[str] = field(doc="Typeahead text")

    _valid_parents: ClassVar[list[str]] = [
        "ContextMenuContent",
        "ContextMenuSubContent",
        "ContextMenuGroup",
    ]

    on_select: EventHandler[no_args_event_spec] = field(doc="Item selected.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a menu item.

        Args:
            *children: Item label.
            **props: shortcut/disabled + standard props.

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


class ContextMenuSeparator(_ContextMenuElement):
    """Separates items."""

    tag = "Separator"
    alias = "RadixPrimitiveContextMenuSeparator"

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


class ContextMenuCheckbox(_ContextMenuElement):
    """A checkbox menu item."""

    tag = "CheckboxItem"
    alias = "RadixPrimitiveContextMenuCheckboxItem"

    checked: Var[bool] = field(doc="Checked state")
    shortcut: Var[str] = field(doc="Right-aligned shortcut")
    disabled: Var[bool] = field(doc="Disable")

    on_select: EventHandler[no_args_event_spec] = field(doc="Selected.")
    on_checked_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Checked change.")


class ContextMenuLabel(_ContextMenuElement):
    """A non-interactive label."""

    tag = "Label"
    alias = "RadixPrimitiveContextMenuLabel"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a menu label.

        Args:
            *children: Label content.
            **props: Standard props.

        Returns:
            The label component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "px-2 py-1 text-xs font-medium text-[var(--gray-11)]",
            existing,
        )
        return super().create(*children, **props)


class ContextMenuGroup(_ContextMenuElement):
    """A group of menu items."""

    tag = "Group"
    alias = "RadixPrimitiveContextMenuGroup"

    _valid_parents: ClassVar[list[str]] = [
        "ContextMenuContent",
        "ContextMenuSubContent",
    ]


class ContextMenuRadioGroup(_ContextMenuElement):
    """A group of radio items."""

    tag = "RadioGroup"
    alias = "RadixPrimitiveContextMenuRadioGroup"

    value: Var[str] = field(doc="Selected value")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[passthrough_event_spec(str)] = field(doc="Value change.")

    _valid_parents: ClassVar[list[str]] = [
        "ContextMenuRadioItem",
        "ContextMenuSubContent",
        "ContextMenuContent",
        "ContextMenuSub",
    ]


class ContextMenuRadioItem(_ContextMenuElement):
    """A radio menu item."""

    tag = "RadioItem"
    alias = "RadixPrimitiveContextMenuRadioItem"

    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    value: Var[str] = field(doc="Item value")
    disabled: Var[bool] = field(doc="Disable")
    text_value: Var[str] = field(doc="Typeahead text")

    on_select: EventHandler[no_args_event_spec] = field(doc="Selected.")


class ContextMenu(ComponentNamespace):
    """ContextMenu components namespace."""

    root = staticmethod(ContextMenuRoot.create)
    trigger = staticmethod(ContextMenuTrigger.create)
    content = staticmethod(ContextMenuContent.create)
    sub = staticmethod(ContextMenuSub.create)
    sub_trigger = staticmethod(ContextMenuSubTrigger.create)
    sub_content = staticmethod(ContextMenuSubContent.create)
    item = staticmethod(ContextMenuItem.create)
    separator = staticmethod(ContextMenuSeparator.create)
    checkbox = staticmethod(ContextMenuCheckbox.create)
    label = staticmethod(ContextMenuLabel.create)
    group = staticmethod(ContextMenuGroup.create)
    radio_group = staticmethod(ContextMenuRadioGroup.create)
    radio = staticmethod(ContextMenuRadioItem.create)


context_menu = ContextMenu()
