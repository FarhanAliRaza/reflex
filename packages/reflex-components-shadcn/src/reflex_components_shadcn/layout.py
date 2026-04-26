"""Layout primitives — container, section, vstack, hstack, separator.

All compile to plain ``<div>`` / ``<section>`` / ``<hr>`` with Tailwind
utilities. No Radix Themes layout CSS imported.
"""

from __future__ import annotations

from typing import Literal

from reflex_base.components.component import Component
from reflex_components_core.el.elements.sectioning import Section
from reflex_components_core.el.elements.typography import Div, Hr

from ._variants import cn, variants

LiteralContainerSize = Literal["sm", "md", "lg", "xl", "full"]


_container_classes = variants(
    base="mx-auto w-full px-4 sm:px-6 lg:px-8",
    defaults={"size": "lg"},
    size={
        "sm": "max-w-2xl",
        "md": "max-w-3xl",
        "lg": "max-w-4xl",
        "xl": "max-w-6xl",
        "full": "max-w-none",
    },
)


class ShadcnContainer(Div):
    """Bounded centered container."""

    @classmethod
    def create(cls, *children, size: LiteralContainerSize = "lg", **props) -> Component:
        """Render a centered max-width container.

        Args:
            *children: Container children.
            size: Max width: ``sm`` / ``md`` / ``lg`` / ``xl`` / ``full``.
            **props: Pass-through.

        Returns:
            The div component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_container_classes(size=size), existing)
        return super().create(*children, **props)


class ShadcnSection(Section):
    """Vertical-rhythm section with shadcn defaults."""

    @classmethod
    def create(cls, *children, **props) -> Component:
        """Render a ``<section>`` with vertical spacing defaults.

        Args:
            *children: Section children.
            **props: Pass-through.

        Returns:
            The section component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("space-y-4 py-6", existing)
        return super().create(*children, **props)


class ShadcnVStack(Div):
    """Vertical flex stack."""

    @classmethod
    def create(cls, *children, gap: int = 4, **props) -> Component:
        """Render a vertical flex stack.

        Args:
            *children: Stack children.
            gap: Tailwind ``space-y`` value (default ``4``).
            **props: Pass-through.

        Returns:
            The div component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(f"flex flex-col space-y-{gap}", existing)
        return super().create(*children, **props)


class ShadcnHStack(Div):
    """Horizontal flex stack."""

    @classmethod
    def create(
        cls, *children, gap: int = 4, align: str = "center", **props
    ) -> Component:
        """Render a horizontal flex stack.

        Args:
            *children: Stack children.
            gap: Tailwind ``gap`` value (default ``4``).
            align: ``items-*`` alignment (default ``center``).
            **props: Pass-through.

        Returns:
            The div component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(f"flex flex-row items-{align} gap-{gap}", existing)
        return super().create(*children, **props)


class ShadcnSeparator(Hr):
    """Horizontal rule."""

    @classmethod
    def create(cls, *children, **props) -> Component:
        """Render a ``<hr>`` with shadcn separator styling.

        Args:
            *children: Ignored (``<hr>`` is void).
            **props: Pass-through.

        Returns:
            The hr component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("my-4 h-px w-full bg-border", existing)
        return super().create(**props)


container = ShadcnContainer.create
section = ShadcnSection.create
vstack = ShadcnVStack.create
hstack = ShadcnHStack.create
separator = ShadcnSeparator.create
