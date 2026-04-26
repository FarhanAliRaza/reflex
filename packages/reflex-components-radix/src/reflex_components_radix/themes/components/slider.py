"""Slider — native ``<input type=range>`` styled with Tailwind utilities.

Multi-thumb sliders aren't representable with a single native range
input; ``default_value`` / ``value`` therefore accept either a number
or a single-item sequence (multi-thumb fall through to the first
value). Apps needing two-thumb sliders should compose two ``rx.slider``
inputs side-by-side.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.event import EventHandler, passthrough_event_spec
from reflex_base.utils.types import typehint_issubclass
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, variants
from reflex_components_radix.themes.base import LiteralAccentColor

on_value_event_spec = (
    passthrough_event_spec(list[float]),
    passthrough_event_spec(list[int]),
)


_slider_classes = variants(
    base=(
        "appearance-none cursor-pointer w-full bg-transparent "
        "[&::-webkit-slider-runnable-track]:h-1 "
        "[&::-webkit-slider-runnable-track]:rounded-full "
        "[&::-webkit-slider-runnable-track]:bg-[var(--gray-a4)] "
        "[&::-webkit-slider-thumb]:appearance-none "
        "[&::-webkit-slider-thumb]:size-4 "
        "[&::-webkit-slider-thumb]:rounded-full "
        "[&::-webkit-slider-thumb]:bg-white "
        "[&::-webkit-slider-thumb]:border-2 "
        "[&::-webkit-slider-thumb]:border-[var(--accent-9)] "
        "[&::-webkit-slider-thumb]:-mt-1.5 "
        "[&::-webkit-slider-thumb]:shadow-sm "
        "[&::-moz-range-track]:h-1 "
        "[&::-moz-range-track]:rounded-full "
        "[&::-moz-range-track]:bg-[var(--gray-a4)] "
        "[&::-moz-range-thumb]:size-4 "
        "[&::-moz-range-thumb]:rounded-full "
        "[&::-moz-range-thumb]:bg-white "
        "[&::-moz-range-thumb]:border-2 "
        "[&::-moz-range-thumb]:border-[var(--accent-9)]"
    ),
    defaults={"size": "2"},
    size={
        "1": "h-3",
        "2": "h-4",
        "3": "h-6",
    },
)


class Slider(elements.Input):
    """Provides user selection from a range of values."""

    tag = "input"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Slider size "1" - "3"')
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    radius: Var[Literal["none", "small", "full"]] = field(doc="Override radius")

    default_value: Var[Sequence[float | int] | float | int] = field(doc="Initial value")
    value: Var[Sequence[float | int]] = field(doc="Controlled value")
    name: Var[str] = field(doc="Form name")
    width: Var[str | None] = field(default=Var.create("100%"), doc="Slider width")
    min: Var[float | int] = field(doc="Min")
    max: Var[float | int] = field(doc="Max")
    step: Var[float | int] = field(doc="Step")
    disabled: Var[bool] = field(doc="Disable")
    orientation: Var[Literal["horizontal", "vertical"]] = field(doc="Orientation")

    _rename_props: ClassVar[dict[str, str]] = {"onChange": "onValueChange"}

    on_change: EventHandler[on_value_event_spec] = field(doc="Fired on value change.")
    on_value_commit: EventHandler[on_value_event_spec] = field(doc="Fired on commit.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a slider input.

        Args:
            *children: Ignored.
            **props: size/min/max/step + standard input props.

        Returns:
            The slider component.
        """
        default_value = props.pop("default_value", [50])
        if isinstance(default_value, Var):
            if typehint_issubclass(default_value._var_type, int | float):
                pass
        elif isinstance(default_value, list) and len(default_value) >= 1:
            default_value = default_value[0]

        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["type"] = "range"
        props["default_value"] = default_value
        props["class_name"] = cn(_slider_classes(**selections), existing)
        return super().create(**props)


slider = Slider.create
