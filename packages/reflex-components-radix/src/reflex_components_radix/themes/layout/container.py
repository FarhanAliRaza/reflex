"""Container — bounded centred content wrapper, Tailwind-styled."""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.style import STACK_CHILDREN_FULL_WIDTH
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, responsive_classes

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
            **props: Container properties. ``size`` accepts ``"1"`` - ``"4"``
                or a Reflex ``Breakpoints`` mapping for responsive widths.

        Returns:
            The container component.
        """
        if stack_children_full_width:
            props["style"] = {**STACK_CHILDREN_FULL_WIDTH, **props.pop("style", {})}
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        size_cls = responsive_classes(size, _SIZE.get)
        # Default to size="3" when nothing translatable was passed (Var, etc.
        # fall through and get put back on the element so any user-supplied
        # runtime expression survives).
        if not size_cls and (size is None or isinstance(size, str)):
            size_cls = _SIZE["3"]
        if size is not None and not isinstance(size, (str, dict)):
            props["size"] = size
        props["class_name"] = cn(f"mx-auto w-full {size_cls}".strip(), existing)
        return super().create(*children, padding=padding, **props)


container = Container.create
