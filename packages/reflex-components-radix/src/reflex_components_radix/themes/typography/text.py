"""Text family — paragraph, span, em, kbd, quote, strong.

All Tailwind-styled, no dependency on ``@radix-ui/themes`` precompiled CSS.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.markdown_component_map import MarkdownComponentMap
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import kbd_classes, text_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

from .base import LiteralTextAlign, LiteralTextSize, LiteralTextTrim, LiteralTextWeight

LiteralType = Literal[
    "p", "label", "div", "span", "b", "i", "u", "abbr", "cite",
    "del", "em", "ins", "kbd", "mark", "s", "samp", "sub", "sup",
]


class Text(elements.Span, MarkdownComponentMap):
    """A foundational text primitive based on the <span> element."""

    tag = "p"

    as_child: Var[bool] = field(doc="Render as child")
    as_: Var[LiteralType] = field(
        default=Var.create("p"),
        doc="Override the rendered element semantically (p|span|label|...)",
    )
    size: Var[Responsive[LiteralTextSize]] = field(doc='Text size: "1" - "9"')
    weight: Var[Responsive[LiteralTextWeight]] = field(doc='Thickness: light|regular|medium|bold')
    align: Var[Responsive[LiteralTextAlign]] = field(doc='Alignment: left|center|right')
    trim: Var[Responsive[LiteralTextTrim]] = field(doc='Trim: normal|start|end|both')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a text element with Tailwind classes.

        Args:
            *children: Text content.
            **props: Standard text props (size, weight, align, etc.).

        Returns:
            The text component.
        """
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        for key in ("size", "weight", "align"):
            value = props.pop(key, None)
            if isinstance(value, str):
                selections[key] = value
            elif value is not None:
                props[key] = value
        props["class_name"] = cn(text_classes(**selections), existing)
        return super().create(*children, **props)


class Span(Text):
    """A variant of text rendering as <span> element."""

    tag = "span"
    as_: Var[LiteralType] = Var.create("span")


class Em(elements.Em):
    """Marks text to stress emphasis."""

    tag = "em"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an emphasized inline span.

        Args:
            *children: The content.
            **props: Standard em props.

        Returns:
            The em component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("italic", existing)
        return super().create(*children, **props)


class Kbd(elements.Kbd):
    """Represents keyboard input or a hotkey."""

    tag = "kbd"

    size: Var[LiteralTextSize] = field(doc='Text size: "1" - "9"')

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a keyboard-input element.

        Args:
            *children: The key label.
            **props: Standard kbd props plus ``size``.

        Returns:
            The kbd component.
        """
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["class_name"] = cn(kbd_classes(**selections), existing)
        return super().create(*children, **props)


class Quote(elements.Q):
    """A short inline quotation."""

    tag = "q"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a quote element.

        Args:
            *children: The quote content.
            **props: Standard q props.

        Returns:
            The q component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("italic", existing)
        return super().create(*children, **props)


class Strong(elements.Strong):
    """Marks text to signify strong importance."""

    tag = "strong"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a strong element.

        Args:
            *children: The content.
            **props: Standard strong props.

        Returns:
            The strong component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("font-bold", existing)
        return super().create(*children, **props)


class TextNamespace(ComponentNamespace):
    """Text components namespace."""

    __call__ = staticmethod(Text.create)
    em = staticmethod(Em.create)
    kbd = staticmethod(Kbd.create)
    quote = staticmethod(Quote.create)
    strong = staticmethod(Strong.create)
    span = staticmethod(Span.create)


text = TextNamespace()
