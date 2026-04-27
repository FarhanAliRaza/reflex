"""Progress — native ``<div role=progressbar>`` styled with Tailwind.

Renders a track div with an inner indicator whose width is computed
from ``value`` / ``max``. No JS, no @radix-ui dependencies.
"""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, variants
from reflex_components_radix.themes.base import LiteralAccentColor

LiteralProgressSize = Literal["1", "2", "3"]


_track_classes = variants(
    base="relative w-full overflow-hidden rounded-full bg-[var(--gray-a3)]",
    defaults={"size": "2"},
    size={
        "1": "h-1",
        "2": "h-1.5",
        "3": "h-2",
    },
)


class Progress(elements.Div):
    """A progress bar component."""

    tag = "div"

    value: Var[int] = field(doc="Current value (0..max)")
    max: Var[int] = field(doc="Maximum value, default 100")
    size: Var[Responsive[LiteralProgressSize]] = field(doc='Size: "1"|"2"|"3"')
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    radius: Var[Literal["none", "small", "medium", "large", "full"]] = field(doc="Radius")
    duration: Var[str] = field(doc="Indeterminate timeout duration")
    fill_color: Var[str] = field(doc="Override fill colour")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a progress bar.

        Args:
            *children: Ignored.
            **props: value/max/size/colour props.

        Returns:
            The progress component.
        """
        size = props.pop("size", "2")
        value = props.pop("value", 0)
        maximum = props.pop("max", 100)
        fill_color = props.pop("fill_color", "var(--accent-9)")
        existing = props.pop("class_name", "")
        size_str = size if isinstance(size, str) else "2"

        props.setdefault("role", "progressbar")
        props["aria-valuemax"] = maximum
        props["aria-valuemin"] = 0
        if isinstance(value, (int, float)):
            props["aria-valuenow"] = value
            width_css = f"{(value / maximum) * 100 if maximum else 0}%"
        else:
            props["aria-valuenow"] = value
            width_css = "var(--progress-value, 0%)"

        indicator = elements.Div.create(
            class_name="h-full transition-all duration-300",
            style={
                "width": width_css,
                "background-color": fill_color,
            },
            data_indicator="",
        )

        props["class_name"] = cn(_track_classes(size=size_str), existing)
        return super().create(indicator, **props)


progress = Progress.create
