"""RadioGroup — native radios styled with Tailwind utilities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.utils import types
from reflex_base.vars.base import LiteralVar, Var
from reflex_base.vars.sequence import StringVar
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.cond import cond
from reflex_components_core.core.foreach import foreach
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import radio_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralSpacing
from reflex_components_radix.themes.layout.flex import Flex
from reflex_components_radix.themes.typography.text import Text

LiteralFlexDirection = Literal["row", "column", "row-reverse", "column-reverse"]


class RadioGroupRoot(elements.Div):
    """A set of radio buttons, only one selectable at a time."""

    tag = "div"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(
        default=LiteralVar.create("2"),
        doc='Size: "1" | "2" | "3"',
    )
    variant: Var[Literal["classic", "surface", "soft"]] = field(
        default=LiteralVar.create("classic"), doc="Variant"
    )
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    value: Var[str] = field(doc="Controlled value")
    default_value: Var[str] = field(doc="Initial value")
    disabled: Var[bool] = field(doc="Disable")
    name: Var[str] = field(doc="Form name")
    required: Var[bool] = field(doc="Required")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[passthrough_event_spec(str)] = field(
        doc="Fired when the selected value changes."
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a radio-group root container.

        Args:
            *children: RadioGroupItem children.
            **props: variant/size/colour props.

        Returns:
            The radio-group root component.
        """
        existing = props.pop("class_name", "")
        props.setdefault("role", "radiogroup")
        props["class_name"] = cn("flex flex-col gap-2", existing)
        return super().create(*children, **props)


class RadioGroupItem(elements.Input):
    """An individual radio in a group."""

    tag = "input"

    value: Var[str] = field(doc="Item value")
    disabled: Var[bool] = field(doc="Disable")
    required: Var[bool] = field(doc="Required")
    name: Var[str] = field(doc="Form name (auto-set by group)")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an individual radio input.

        Args:
            *children: Ignored.
            **props: value + standard radio props.

        Returns:
            The radio component.
        """
        existing = props.pop("class_name", "")
        props["type"] = "radio"
        props["class_name"] = cn(radio_classes(), "appearance-none", existing)
        return super().create(**props)


class HighLevelRadioGroup(RadioGroupRoot):
    """High-level wrapper for RadioGroup taking a list of values."""

    items: Var[Sequence[str]] = field(doc="The items of the radio group.")
    direction: Var[LiteralFlexDirection] = field(
        default=LiteralVar.create("row"), doc="Layout direction"
    )
    spacing: Var[LiteralSpacing] = field(default=LiteralVar.create("2"), doc="Gap")

    @classmethod
    def create(
        cls,
        items: Var[Sequence[str | int | float | list | dict | bool | None]],
        **props: Any,
    ) -> Component:
        """Create a radio group from a list of items.

        Args:
            items: The items to render.
            **props: variant/size/colour/value props.

        Returns:
            The radio group component.

        Raises:
            TypeError: If items is not a list or Var of list.
        """
        direction = props.pop("direction", "row")
        spacing = props.pop("spacing", "2")
        size = props.pop("size", "2")
        default_value = props.pop("default_value", "")

        if not isinstance(items, (list, Var)) or (
            isinstance(items, Var)
            and not types.typehint_issubclass(items._var_type, list)
        ):
            items_type = type(items) if not isinstance(items, Var) else items._var_type
            msg = f"The radio group component takes in a list, got {items_type} instead"
            raise TypeError(msg)

        default_value_var = LiteralVar.create(default_value)
        if isinstance(default_value, str) or (
            isinstance(default_value, Var) and default_value._var_type is str
        ):
            default_value_var = LiteralVar.create(default_value)
        else:
            default_value_var = LiteralVar.create(default_value).to_string()

        def radio_group_item(value: Var) -> Component:
            item_value = cond(
                value.js_type() == "string",
                value,
                value.to_string(),
            ).to(StringVar)
            return Text.create(
                Flex.create(
                    RadioGroupItem.create(
                        value=item_value,
                        disabled=props.get("disabled", LiteralVar.create(False)),
                    ),
                    item_value,
                    spacing="2",
                    align="center",
                ),
                size=size,
                as_="label",
            )

        children = [foreach(items, radio_group_item)]
        return RadioGroupRoot.create(
            Flex.create(*children, direction=direction, spacing=spacing),
            size=size,
            default_value=default_value_var,
            **props,
        )


class RadioGroup(ComponentNamespace):
    """RadioGroup components namespace."""

    root = staticmethod(RadioGroupRoot.create)
    item = staticmethod(RadioGroupItem.create)
    __call__ = staticmethod(HighLevelRadioGroup.create)


radio = radio_group = RadioGroup()
