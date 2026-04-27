"""Switch — toggle styled as a slider, native ``<input type=checkbox>``.

Renders a hidden checkbox + visual track/thumb spans so the control
gets full keyboard / form behaviour without any JS, and it tints with
``--accent-9`` when checked.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, variants
from reflex_components_radix.themes.base import LiteralAccentColor

LiteralSwitchSize = Literal["1", "2", "3"]


_track_classes = variants(
    base=(
        "relative inline-flex shrink-0 cursor-pointer rounded-full "
        "transition-colors duration-150 "
        "bg-[var(--gray-a5)] "
        "has-[input:checked]:bg-[var(--accent-9)] "
        "has-[input:disabled]:cursor-not-allowed has-[input:disabled]:opacity-50"
    ),
    defaults={"size": "2"},
    size={
        "1": "h-4 w-7",
        "2": "h-5 w-9",
        "3": "h-6 w-11",
    },
)
_thumb_classes = variants(
    base=(
        "absolute top-1/2 -translate-y-1/2 left-0.5 "
        "rounded-full bg-white shadow-sm "
        "transition-transform duration-150 "
        "peer-checked:translate-x-full"
    ),
    defaults={"size": "2"},
    size={
        "1": "size-3",
        "2": "size-4",
        "3": "size-5",
    },
)


class Switch(elements.Label):
    """A toggle switch (visual checkbox)."""

    tag = "label"

    default_checked: Var[bool] = field(doc="Default checked")
    checked: Var[bool] = field(doc="Checked state")
    disabled: Var[bool] = field(doc="Disable")
    required: Var[bool] = field(doc="Required")
    name: Var[str] = field(doc="Form name")
    value: Var[str] = field(doc='Form value when on')
    size: Var[Responsive[LiteralSwitchSize]] = field(doc='Size "1" - "3"')
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    radius: Var[Literal["none", "small", "full"]] = field(doc="Radius override")

    _rename_props: ClassVar[dict[str, str]] = {
        "onChange": "onCheckedChange",
        "colorScheme": "data-accent-color",
    }

    on_change: EventHandler[passthrough_event_spec(bool)] = field(
        doc="Fired when toggle state changes"
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a switch.

        Args:
            *children: Ignored.
            **props: Standard checkbox props plus size.

        Returns:
            The switch component.
        """
        size = props.pop("size", "2")
        size_str = size if isinstance(size, str) else "2"

        # The hidden checkbox gets the form props; track + thumb are visual only.
        input_props = {
            "type": "checkbox",
            "class_name": "peer sr-only",
        }
        for key in (
            "checked", "default_checked", "disabled", "required",
            "name", "value", "on_change",
        ):
            if key in props:
                input_props[key] = props.pop(key)

        input_el = elements.Input.create(**input_props)
        thumb = elements.Span.create(class_name=_thumb_classes(size=size_str))

        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            _track_classes(size=size_str),
            "items-center",
            existing,
        )
        return super().create(input_el, thumb, **props)


switch = Switch.create
