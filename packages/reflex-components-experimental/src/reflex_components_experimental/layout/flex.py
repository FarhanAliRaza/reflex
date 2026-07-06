"""Radix-parity Flex container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, FLEX_DIR, JUSTIFY
from reflex_components_experimental.utils import merge_class_name


def flex(
    *children,
    direction: str | None = None,
    gap: str | None = None,
    spacing: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Flex container.

    Args:
        *children: Child components.
        direction: Flex direction.
        gap: Gap between children, kept as a CSS-style alias.
        spacing: Radix-compatible alias for ``gap``.
        align: Cross-axis alignment.
        justify: Main-axis alignment.
        **props: Additional div props.

    Returns:
        The rendered component.
    """
    classes = ["flex box-border"]
    if direction:
        classes.append(FLEX_DIR[direction])
    effective_gap = spacing if spacing is not None else gap
    if effective_gap is not None:
        # Radix maps gap "0" to a literal 0; there is no --space-0 token.
        classes.append(
            "gap-0" if effective_gap == "0" else f"gap-[var(--space-{effective_gap})]"
        )
    classes.extend([
        ALIGN[align] if align else "items-stretch",
        JUSTIFY[justify] if justify else "justify-start",
    ])
    merge_class_name(" ".join(classes), props)
    return rx.el.div(*children, **props)
