"""Inset — negative-margin wrapper letting content bleed into a Card."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn

LiteralInsetSide = Literal["x", "y", "top", "bottom", "right", "left"]


_SIDE = {
    "x": "-mx-[var(--inset-padding-bottom)]",
    "y": "-my-[var(--inset-padding-bottom)]",
    "top": "-mt-[var(--inset-padding-top)]",
    "bottom": "-mb-[var(--inset-padding-bottom)]",
    "left": "-ml-[var(--inset-padding-left)]",
    "right": "-mr-[var(--inset-padding-right)]",
}


class Inset(elements.Div):
    """Applies a negative margin to allow content to bleed into the surrounding container."""

    tag = "div"

    side: Var[Responsive[LiteralInsetSide]] = field(doc="Which side(s) to inset")
    clip: Var[Responsive[Literal["border-box", "padding-box"]]] = field(doc="Clip box")
    p: Var[Responsive[int | str]] = field(doc="Padding")
    px: Var[Responsive[int | str]] = field(doc="Padding x")
    py: Var[Responsive[int | str]] = field(doc="Padding y")
    pt: Var[Responsive[int | str]] = field(doc="Padding top")
    pr: Var[Responsive[int | str]] = field(doc="Padding right")
    pb: Var[Responsive[int | str]] = field(doc="Padding bottom")
    pl: Var[Responsive[int | str]] = field(doc="Padding left")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an inset wrapper.

        Args:
            *children: Content to inset.
            **props: side/clip + standard div props.

        Returns:
            The inset component.
        """
        side = props.pop("side", None)
        existing = props.pop("class_name", "")
        parts: list[str] = []
        if isinstance(side, str):
            parts.append(_SIDE.get(side, "-mx-4 -my-4"))
        elif side is not None:
            props["side"] = side
        else:
            parts.append("-m-4")
        props["class_name"] = cn(" ".join(parts), existing)
        return super().create(*children, **props)


inset = Inset.create
