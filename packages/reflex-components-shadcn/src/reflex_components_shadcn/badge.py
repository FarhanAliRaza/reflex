"""shadcn-style badge component."""

from __future__ import annotations

from typing import Literal

from reflex_base.components.component import Component
from reflex_components_core.el.elements.typography import Div

from ._variants import cn, variants

LiteralBadgeVariant = Literal["default", "secondary", "destructive", "outline"]


_badge_classes = variants(
    base=(
        "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs "
        "font-semibold transition-colors focus:outline-none focus:ring-2 "
        "focus:ring-ring focus:ring-offset-2"
    ),
    defaults={"variant": "default"},
    variant={
        "default": (
            "border-transparent bg-primary text-primary-foreground "
            "shadow hover:bg-primary/80"
        ),
        "secondary": (
            "border-transparent bg-secondary text-secondary-foreground "
            "hover:bg-secondary/80"
        ),
        "destructive": (
            "border-transparent bg-destructive text-destructive-foreground "
            "shadow hover:bg-destructive/80"
        ),
        "outline": "text-foreground",
    },
)


class ShadcnBadge(Div):
    """A small inline pill, useful for tags / status / labels."""

    @classmethod
    def create(
        cls, *children, variant: LiteralBadgeVariant = "default", **props
    ) -> Component:
        """Render a shadcn-style badge.

        Args:
            *children: Badge content.
            variant: ``default``, ``secondary``, ``destructive``, or
                ``outline``.
            **props: Pass-through to the underlying ``<div>``.

        Returns:
            The badge component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_badge_classes(variant=variant), existing)
        return super().create(*children, **props)


badge = ShadcnBadge.create
