"""Section — vertical-rhythm wrapper, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, responsive_classes

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
        doc='Section size: "1" - "3"',
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a section.

        Args:
            *children: Section content.
            **props: Standard section props plus ``size`` (``"1"`` - ``"3"``,
                or a Reflex ``Breakpoints`` mapping).

        Returns:
            The section component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        size_cls = responsive_classes(size, _SIZE.get)
        if not size_cls and (size is None or isinstance(size, str)):
            size_cls = _SIZE["2"]
        if size is not None and not isinstance(size, (str, dict)):
            props["size"] = size
        props["class_name"] = cn(size_cls, existing)
        return super().create(*children, **props)


section = Section.create
