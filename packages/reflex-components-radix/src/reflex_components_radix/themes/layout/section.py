"""Section — vertical-rhythm wrapper, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn

LiteralSectionSize = Literal["1", "2", "3"]


_SIZE = {
    "1": "py-6",
    "2": "py-12",
    "3": "py-24",
}


class Section(elements.Section):
    """Denotes a section of page content."""

    tag = "section"

    size: Var[Responsive[LiteralSectionSize]] = field(
        default=LiteralVar.create("2"),
        doc='Section size: "1" - "3"',
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a section.

        Args:
            *children: Section content.
            **props: Standard section props plus size.

        Returns:
            The section component.
        """
        size = props.pop("size", "2")
        existing = props.pop("class_name", "")
        size_class = _SIZE.get(size, _SIZE["2"]) if isinstance(size, str) else _SIZE["2"]
        if not isinstance(size, str) and size is not None:
            props["size"] = size
        props["class_name"] = cn(size_class, existing)
        return super().create(*children, **props)


section = Section.create
