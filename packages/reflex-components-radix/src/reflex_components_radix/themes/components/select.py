"""Select — native ``<select>`` styled with Tailwind utilities.

The original Radix Themes Select supported a custom popup positioned
via portal, but a native ``<select>`` keeps the same call sites
working (``rx.select(items, default_value=...)``) without any JS or
@radix-ui/react-select dependency. Apps that need the fancy popup +
keyboard navigation can compose that themselves on top of dropdown_menu
in a follow-up.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.foreach import foreach
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import select_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralRadius


class SelectRoot(elements.Select):
    """Native ``<select>`` element wired to the Reflex Select API."""

    tag = "select"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size: "1"|"2"|"3"')
    default_value: Var[str] = field(doc="Initial value")
    value: Var[str] = field(doc="Controlled value")
    default_open: Var[bool] = field(doc="(no-op for native select)")
    open: Var[bool] = field(doc="(no-op for native select)")
    name: Var[str] = field(doc="Form name")
    disabled: Var[bool] = field(doc="Disable")
    required: Var[bool] = field(doc="Required")
    variant: Var[Literal["classic", "surface", "soft", "ghost"]] = field(doc="Variant")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[passthrough_event_spec(str)] = field(doc="Value change.")
    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="(unused).")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a native ``<select>``.

        Args:
            *children: ``<option>`` elements.
            **props: variant/size/colour + standard select props.

        Returns:
            The select component.
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
        props["class_name"] = cn(select_classes(**selections), existing)
        return super().create(*children, **props)


class SelectTrigger(elements.Div):
    """No-op kept for API compatibility — native select renders its own trigger."""

    tag = "div"

    variant: Var[Literal["classic", "surface", "soft", "ghost"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    radius: Var[LiteralRadius] = field(doc="Radius")
    placeholder: Var[str] = field(doc="Trigger placeholder")

    _valid_parents: ClassVar[list[str]] = ["SelectRoot"]
    _memoization_mode = MemoizationMode(recursive=False)


class SelectContent(elements.Div):
    """No-op kept for API compatibility — items live directly in ``<select>``."""

    tag = "div"

    variant: Var[Literal["solid", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    position: Var[Literal["item-aligned", "popper"]] = field(doc="Position")
    side: Var[Literal["top", "right", "bottom", "left"]] = field(doc="Side")
    side_offset: Var[int] = field(doc="Side offset")
    align: Var[Literal["start", "center", "end"]] = field(doc="Align")
    align_offset: Var[int] = field(doc="Align offset")

    on_close_auto_focus: EventHandler[no_args_event_spec] = field(doc="(unused).")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="(unused).")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="(unused).")


class SelectGroup(elements.Optgroup):
    """Wraps a group of select items."""

    tag = "optgroup"

    _valid_parents: ClassVar[list[str]] = ["SelectRoot", "SelectContent"]


class SelectItem(elements.Option):
    """An ``<option>`` inside a select."""

    tag = "option"

    value: Var[str] = field(doc="Item value")
    disabled: Var[bool] = field(doc="Disable")

    _valid_parents: ClassVar[list[str]] = ["SelectGroup", "SelectContent", "SelectRoot"]


class SelectLabel(elements.Optgroup):
    """A group label (rendered as <optgroup label=...>)."""

    tag = "optgroup"

    _valid_parents: ClassVar[list[str]] = ["SelectGroup"]


class SelectSeparator(elements.Hr):
    """Visual separator inside the popup (no-op for native select)."""

    tag = "hr"


class HighLevelSelect(SelectRoot):
    """High level wrapper taking a list of items."""

    items: Var[Sequence[str]] = field(doc="The items of the select.")
    placeholder: Var[str] = field(doc="The placeholder of the select.")
    label: Var[str] = field(doc="The label of the select.")
    color_scheme: Var[LiteralAccentColor] = field(doc="Accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    radius: Var[LiteralRadius] = field(doc="Radius")
    width: Var[str] = field(doc="Width")
    position: Var[Literal["item-aligned", "popper"]] = field(doc="Position")

    @classmethod
    def create(
        cls, items: list[str] | Var[list[str]], **props: Any,
    ) -> Component:
        """Create a high-level select.

        Args:
            items: The select items.
            **props: variant/size/value/placeholder etc.

        Returns:
            The select component.
        """
        label = props.pop("label", None)
        placeholder = props.pop("placeholder", None)

        if isinstance(items, Var):
            options = [
                foreach(items, lambda item: SelectItem.create(item, value=item))
            ]
        else:
            options = [SelectItem.create(item, value=item) for item in items]

        children: list[Component | str] = []
        if placeholder is not None:
            children.append(
                SelectItem.create(placeholder, value="", disabled=True)
            )
        if label is not None:
            children.append(SelectGroup.create(*options, label=label))
        else:
            children.extend(options)

        return SelectRoot.create(*children, **props)


class Select(ComponentNamespace):
    """Select components namespace."""

    root = staticmethod(SelectRoot.create)
    trigger = staticmethod(SelectTrigger.create)
    content = staticmethod(SelectContent.create)
    group = staticmethod(SelectGroup.create)
    item = staticmethod(SelectItem.create)
    separator = staticmethod(SelectSeparator.create)
    label = staticmethod(SelectLabel.create)
    __call__ = staticmethod(HighLevelSelect.create)


select = Select()
