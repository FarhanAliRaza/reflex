"""Spinner — Tailwind-styled CSS spinner (no JS)."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import spinner_classes
from reflex_components_radix._variants import cn

LiteralSpinnerSize = Literal["1", "2", "3"]


class Spinner(elements.Span):
    """A spinner component."""

    tag = "span"
    is_default = False

    size: Var[Responsive[LiteralSpinnerSize]] = field(doc="The size of the spinner.")
    loading: Var[bool] = field(doc="If False, hides the spinner.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a spinner element.

        Args:
            *children: Ignored.
            **props: size + standard span props.

        Returns:
            The spinner component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props.setdefault("role", "status")
        props["class_name"] = cn(spinner_classes(**selections), existing)
        return super().create(**props)


spinner = Spinner.create
