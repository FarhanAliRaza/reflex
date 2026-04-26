"""shadcn-style button component.

Compiles to a plain ``<button>`` element with Tailwind utility classes.
No third-party CSS, no Radix Themes import. Variants and sizes resolve at
Python compile time so the JSX output is a single class-name string the
Tailwind JIT can pick up.
"""

from __future__ import annotations

from typing import Literal

from reflex_base.components.component import Component
from reflex_components_core.el.elements.forms import Button as ElButton

from ._variants import cn, variants

LiteralVariant = Literal[
    "default", "destructive", "outline", "secondary", "ghost", "link"
]
LiteralSize = Literal["default", "sm", "lg", "icon"]


_button_classes = variants(
    base=(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap "
        "rounded-md text-sm font-medium transition-colors "
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring "
        "disabled:pointer-events-none disabled:opacity-50"
    ),
    defaults={"variant": "default", "size": "default"},
    variant={
        "default": ("bg-primary text-primary-foreground shadow hover:bg-primary/90"),
        "destructive": (
            "bg-destructive text-destructive-foreground shadow-sm "
            "hover:bg-destructive/90"
        ),
        "outline": (
            "border border-input bg-background shadow-sm "
            "hover:bg-accent hover:text-accent-foreground"
        ),
        "secondary": (
            "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80"
        ),
        "ghost": "hover:bg-accent hover:text-accent-foreground",
        "link": "text-primary underline-offset-4 hover:underline",
    },
    size={
        "default": "h-9 px-4 py-2",
        "sm": "h-8 rounded-md px-3 text-xs",
        "lg": "h-10 rounded-md px-8",
        "icon": "h-9 w-9",
    },
)


class ShadcnButton(ElButton):
    """A button styled with shadcn/ui's Tailwind variants."""

    @classmethod
    def create(
        cls,
        *children,
        variant: LiteralVariant = "default",
        size: LiteralSize = "default",
        **props,
    ) -> Component:
        """Create a shadcn-style button.

        Args:
            *children: Button label / icon children.
            variant: Visual variant. One of ``default``, ``destructive``,
                ``outline``, ``secondary``, ``ghost``, ``link``.
            size: Button size. One of ``default``, ``sm``, ``lg``, ``icon``.
            **props: Standard ``<button>`` props plus ``class_name`` to
                append additional Tailwind utilities.

        Returns:
            The button component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_button_classes(variant=variant, size=size), existing)
        return super().create(*children, **props)


button = ShadcnButton.create
