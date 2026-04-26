"""shadcn-style button component.

Compiles to a plain ``<button>`` with Tailwind utilities only — no
``@radix-ui/themes`` precompiled CSS. Variant / size resolve at Python
compile time so the JSX is a single class-name string the Tailwind JIT
picks up.

The variants reference Radix's ``--accent-*`` / ``--gray-*`` CSS
variables via Tailwind v4 arbitrary-value syntax (``bg-[var(--accent-9)]``).
Those variables are already emitted on the ``[data-accent-color]`` /
``[data-gray-color]`` selectors that Radix Themes' tokens.css writes
once at the page root, so the button automatically tints to whatever
``accent_color`` the user configured on ``rx.theme(...)`` — no extra
Tailwind config required, no extra CSS shipped.
"""

from __future__ import annotations

from typing import Literal

from reflex_base.components.component import Component
from reflex_components_core.el.elements.forms import Button as ElButton

from ._variants import cn, variants

LiteralVariant = Literal[
    "default", "destructive", "outline", "secondary", "ghost", "link"
]
LiteralSize = Literal["default", "sm", "lg", "xl", "icon"]


_button_classes = variants(
    base=(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap "
        "rounded-(--radius-3) text-sm font-medium transition-colors "
        "focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:pointer-events-none disabled:opacity-50 cursor-pointer"
    ),
    defaults={"variant": "default", "size": "default"},
    variant={
        "default": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] "
            "shadow-sm hover:bg-[var(--accent-10)]"
        ),
        "destructive": (
            "bg-[var(--red-9)] text-white shadow-sm hover:bg-[var(--red-10)]"
        ),
        "outline": (
            "border border-[var(--accent-a8)] bg-transparent "
            "text-[var(--accent-11)] "
            "hover:bg-[var(--accent-a3)]"
        ),
        "secondary": (
            "bg-[var(--accent-3)] text-[var(--accent-11)] "
            "hover:bg-[var(--accent-4)]"
        ),
        "ghost": (
            "bg-transparent text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "link": (
            "bg-transparent text-[var(--accent-11)] "
            "underline-offset-4 hover:underline shadow-none"
        ),
    },
    size={
        "default": "h-8 px-3 text-sm",
        "sm": "h-6 px-2 text-xs",
        "lg": "h-10 px-5 text-base",
        "xl": "h-12 px-6 text-base",
        "icon": "h-8 w-8",
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
