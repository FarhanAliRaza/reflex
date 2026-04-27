"""Container — bounded centred content wrapper, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.style import STACK_CHILDREN_FULL_WIDTH
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn

LiteralContainerSize = Literal["1", "2", "3", "4"]


_SIZE = {
    "1": "max-w-[448px]",
    "2": "max-w-[688px]",
    "3": "max-w-[880px]",
    "4": "max-w-[1136px]",
}


class Container(elements.Div):
    """Constrains the maximum width of page content."""

    tag = "div"

    size: Var[Responsive[LiteralContainerSize]] = field(
        default=LiteralVar.create("3"),
        doc='Container size: "1" - "4"',
    )

    @classmethod
    def create(
        cls,
        *children: Any,
        padding: str = "16px",
        stack_children_full_width: bool = False,
        **props: Any,
    ) -> Component:
        """Create a container.

        Args:
            *children: Children components.
            padding: Container padding.
            stack_children_full_width: If True, child stacks span full width.
            **props: Container properties.

        Returns:
            The container component.
        """
        if stack_children_full_width:
            props["style"] = {**STACK_CHILDREN_FULL_WIDTH, **props.pop("style", {})}
        size = props.pop("size", "3")
        existing = props.pop("class_name", "")
        size_class = _SIZE.get(size, _SIZE["3"]) if isinstance(size, str) else ""
        if not isinstance(size, str) and size is not None:
            props["size"] = size
        props["class_name"] = cn(
            f"mx-auto w-full {size_class}".strip(), existing
        )
        return super().create(*children, padding=padding, **props)


container = Container.create
