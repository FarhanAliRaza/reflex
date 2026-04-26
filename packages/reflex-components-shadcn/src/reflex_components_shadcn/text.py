"""shadcn-style text / paragraph helpers.

Compile to ``<p>`` with the typographic defaults from shadcn/ui's
typography stack: ``leading-7``, optional ``[&:not(:first-child)]:mt-6``
for prose flow.
"""

from __future__ import annotations

from typing import Literal

from reflex_base.components.component import Component
from reflex_components_core.el.elements.inline import Span
from reflex_components_core.el.elements.typography import P

from ._variants import cn, variants

LiteralTextSize = Literal["xs", "sm", "base", "lg", "xl"]
LiteralTextWeight = Literal["normal", "medium", "semibold", "bold"]
LiteralTextMuted = Literal["default", "muted", "subtle"]


_text_classes = variants(
    base="",
    defaults={"size": "base", "weight": "normal", "tone": "default"},
    size={
        "xs": "text-xs",
        "sm": "text-sm",
        "base": "text-base",
        "lg": "text-lg",
        "xl": "text-xl",
    },
    weight={
        "normal": "font-normal",
        "medium": "font-medium",
        "semibold": "font-semibold",
        "bold": "font-bold",
    },
    tone={
        "default": "text-foreground",
        "muted": "text-muted-foreground",
        "subtle": "text-muted-foreground/80",
    },
)


_PROSE_BASE = "leading-7"


class ShadcnParagraph(P):
    """A ``<p>`` styled with shadcn typography defaults."""

    @classmethod
    def create(
        cls,
        *children,
        size: LiteralTextSize = "base",
        weight: LiteralTextWeight = "normal",
        tone: LiteralTextMuted = "default",
        **props,
    ) -> Component:
        """Render shadcn-style prose paragraph.

        Args:
            *children: Inline children.
            size: Text size.
            weight: Font weight.
            tone: ``default`` (foreground), ``muted``, or ``subtle``.
            **props: Pass-through to the underlying ``<p>``.

        Returns:
            The paragraph component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            _PROSE_BASE, _text_classes(size=size, weight=weight, tone=tone), existing
        )
        return super().create(*children, **props)


class ShadcnText(Span):
    """A ``<span>`` styled with shadcn typography variants (inline use)."""

    @classmethod
    def create(
        cls,
        *children,
        size: LiteralTextSize = "base",
        weight: LiteralTextWeight = "normal",
        tone: LiteralTextMuted = "default",
        **props,
    ) -> Component:
        """Render shadcn-style inline text.

        Args:
            *children: Inline children.
            size: Text size.
            weight: Font weight.
            tone: Color tone.
            **props: Pass-through to the underlying ``<span>``.

        Returns:
            The span component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            _text_classes(size=size, weight=weight, tone=tone), existing
        )
        return super().create(*children, **props)


paragraph = ShadcnParagraph.create
text = ShadcnText.create
