"""Checkbox — native ``<input type=checkbox>`` styled with Tailwind utilities.

Public API matches the original Radix Themes Checkbox + HighLevelCheckbox.
``rx.checkbox(text="Label", checked=...)`` keeps working unchanged.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import checkbox_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralSpacing
from reflex_components_radix.themes.layout.flex import Flex
from reflex_components_radix.themes.typography.text import Text

LiteralCheckboxSize = Literal["1", "2", "3"]
LiteralCheckboxVariant = Literal["classic", "surface", "soft"]


class Checkbox(elements.Input):
    """Selects a single boolean value, typically for submission in a form."""

    tag = "input"

    size: Var[Responsive[LiteralCheckboxSize]] = field(doc='Size "1" - "3"')
    variant: Var[LiteralCheckboxVariant] = field(doc='Variant: classic|surface|soft')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")
    default_checked: Var[bool] = field(doc="Initial checked state")
    checked: Var[bool] = field(doc="Controlled checked state")
    disabled: Var[bool] = field(doc="Disabled state")
    required: Var[bool] = field(doc="Required for form submission")
    name: Var[str] = field(doc="Form name")
    value: Var[str] = field(doc="Form value")

    _rename_props: ClassVar[dict[str, str]] = {
        "onChange": "onCheckedChange",
        "colorScheme": "data-accent-color",
    }

    on_change: EventHandler[passthrough_event_spec(bool)] = field(
        doc="Fired when checked or unchecked."
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a checkbox input.

        Args:
            *children: Ignored.
            **props: variant/size + standard checkbox props.

        Returns:
            The checkbox component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["type"] = "checkbox"
        props["class_name"] = cn(
            checkbox_classes(**selections),
            "appearance-none",
            existing,
        )
        return super().create(**props)


class HighLevelCheckbox(Checkbox):
    """A checkbox with a label."""

    text: Var[str] = field(doc="The label text.")
    spacing: Var[LiteralSpacing] = field(doc="Gap between checkbox and label.")

    @classmethod
    def create(cls, text: Var[str] = Var.create(""), **props: Any) -> Component:
        """Create a checkbox + label pair.

        Args:
            text: The label text.
            **props: Checkbox props.

        Returns:
            The labelled-checkbox component.
        """
        spacing = props.pop("spacing", "2")
        size = props.pop("size", "2")
        flex_props: dict[str, Any] = {}
        if "gap" in props:
            flex_props["gap"] = props.pop("gap", None)
        return Text.create(
            Flex.create(
                Checkbox.create(size=size, **props),
                text,
                spacing=spacing,
                align="center",
                **flex_props,
            ),
            as_="label",
            size=size,
        )


class CheckboxNamespace(ComponentNamespace):
    """Checkbox components namespace."""

    __call__ = staticmethod(HighLevelCheckbox.create)


checkbox = CheckboxNamespace()
