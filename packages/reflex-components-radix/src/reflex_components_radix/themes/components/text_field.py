"""TextField — native ``<input>`` with Tailwind utility classes.

Public API matches the original ``TextField.Root`` / ``TextField.Slot``
namespace so existing call sites keep working. The slot wraps the
input in a relatively-positioned div so absolute-positioned icons sit
inside the field.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.event import EventHandler, input_event, key_event
from reflex_base.utils.types import is_optional
from reflex_base.vars.base import Var
from reflex_base.vars.number import ternary_operation
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.debounce import DebounceInput
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import text_field_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralRadius

LiteralTextFieldSize = Literal["1", "2", "3"]
LiteralTextFieldVariant = Literal["classic", "surface", "soft"]


class TextFieldRoot(elements.Input):
    """Captures user input."""

    tag = "input"

    size: Var[Responsive[LiteralTextFieldSize]] = field(doc='Field size "1" - "3"')
    variant: Var[LiteralTextFieldVariant] = field(doc='Variant: classic|surface|soft')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    radius: Var[LiteralRadius] = field(doc="Override theme radius")

    auto_complete: Var[bool] = field(doc="Enable autocomplete")
    default_value: Var[str] = field(doc="Initial value")
    disabled: Var[bool] = field(doc="Disable input")
    max_length: Var[int] = field(doc="Max chars")
    min_length: Var[int] = field(doc="Min chars")
    name: Var[str] = field(doc="Form name")
    placeholder: Var[str] = field(doc="Placeholder text")
    read_only: Var[bool] = field(doc="Read-only")
    required: Var[bool] = field(doc="Required")
    type: Var[str] = field(doc="Input type")
    value: Var[str | int | float] = field(doc="Input value")
    list: Var[str] = field(doc="Datalist id")

    on_change: EventHandler[input_event] = field(doc="Value change.")
    on_focus: EventHandler[input_event] = field(doc="Focus.")
    on_blur: EventHandler[input_event] = field(doc="Blur.")
    on_key_down: EventHandler[key_event] = field(doc="Key down.")
    on_key_up: EventHandler[key_event] = field(doc="Key up.")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a text input.

        Args:
            *children: Ignored (input is void).
            **props: Standard input props plus variant/size/colour.

        Returns:
            The text-field component (debounced if controlled).
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
        props["class_name"] = cn(text_field_classes(**selections), existing)

        value = props.get("value")
        if value is not None and is_optional((value_var := Var.create(value))._var_type):
            value_var_is_not_none = value_var != Var.create(None)
            value_var_is_not_undefined = value_var != Var(_js_expr="undefined")
            props["value"] = ternary_operation(
                value_var_is_not_none & value_var_is_not_undefined,
                value,
                Var.create(""),
            )

        component = super().create(*children, **props)
        if props.get("value") is not None and props.get("on_change") is not None:
            return DebounceInput.create(component)
        return component


class TextFieldSlot(elements.Div):
    """Wrapper for icons or buttons positioned inside a TextField."""

    tag = "div"

    color_scheme: Var[LiteralAccentColor] = field(doc="Slot accent color")
    side: Var[Literal["left", "right"]] = field(doc="Slot side: left|right")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a text-field slot wrapper.

        Args:
            *children: Slot icon/button.
            **props: ``side`` plus standard div props.

        Returns:
            The slot component.
        """
        side = props.pop("side", "left")
        existing = props.pop("class_name", "")
        position = "left-2" if side == "left" else "right-2"
        props["class_name"] = cn(
            f"absolute top-1/2 -translate-y-1/2 {position} "
            "flex items-center text-[var(--gray-11)]",
            existing,
        )
        return super().create(*children, **props)


class TextField(ComponentNamespace):
    """TextField components namespace."""

    slot = staticmethod(TextFieldSlot.create)
    __call__ = staticmethod(TextFieldRoot.create)


input = text_field = TextField()
