"""Stack components."""

from __future__ import annotations

from typing import ClassVar

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive

from reflex_components_radix.themes.base import LiteralAlign, LiteralSpacing

from .flex import Flex, LiteralFlexDirection


class Stack(Flex):
    """A stack component."""

    spacing: Var[Responsive[LiteralSpacing]] = field(
        doc="The spacing between each stack item."
    )

    align: Var[Responsive[LiteralAlign]] = field(
        doc="The alignment of the stack items."
    )

    _layout_defaults: ClassVar[dict[str, str]] = {"spacing": "3", "align": "start"}

    @classmethod
    def create(
        cls,
        *children,
        **props,
    ) -> Component:
        """Create a new instance of the component.

        Args:
            *children: The children of the stack.
            **props: The properties of the stack.

        Returns:
            The stack component.
        """
        for key, default in cls._layout_defaults.items():
            props.setdefault(key, default)

        given_class_name = props.pop("class_name", [])
        if not isinstance(given_class_name, list):
            given_class_name = [given_class_name]
        props["class_name"] = ["rx-Stack", *given_class_name]

        return super().create(
            *children,
            **props,
        )


class VStack(Stack):
    """A vertical stack component."""

    direction: Var[Responsive[LiteralFlexDirection]] = field(
        doc="The direction of the stack."
    )

    _layout_defaults: ClassVar[dict[str, str]] = {
        **Stack._layout_defaults,
        "direction": "column",
    }


class HStack(Stack):
    """A horizontal stack component."""

    direction: Var[Responsive[LiteralFlexDirection]] = field(
        doc="The direction of the stack."
    )

    _layout_defaults: ClassVar[dict[str, str]] = {
        **Stack._layout_defaults,
        "direction": "row",
    }


stack = Stack.create
hstack = HStack.create
vstack = VStack.create
