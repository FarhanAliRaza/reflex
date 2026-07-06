"""Radix-parity Grid container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, JUSTIFY
from reflex_components_experimental.utils import merge_class_name


def grid(
    *children,
    columns: str | None = None,
    gap: str | None = None,
    gap_x: str | None = None,
    gap_y: str | None = None,
    spacing: str | None = None,
    spacing_x: str | None = None,
    spacing_y: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Grid container.

    Args:
        *children: Child components.
        columns: Number of grid columns.
        gap: Gap between children, kept as a CSS-style alias.
        gap_x: Horizontal gap alias.
        gap_y: Vertical gap alias.
        spacing: Radix-compatible alias for ``gap``.
        spacing_x: Radix-compatible alias for ``gap_x``.
        spacing_y: Radix-compatible alias for ``gap_y``.
        align: Cross-axis alignment.
        justify: Main-axis alignment.
        **props: Additional div props.

    Returns:
        The rendered component.
    """
    classes = ["grid box-border", "[grid-template-rows:none]"]
    if columns and columns != "1":
        classes.append(f"[grid-template-columns:repeat({columns},minmax(0,1fr))]")
    else:
        classes.append("[grid-template-columns:minmax(0,1fr)]")
    effective_gap = spacing if spacing is not None else gap
    effective_gap_x = spacing_x if spacing_x is not None else gap_x
    effective_gap_y = spacing_y if spacing_y is not None else gap_y
    if effective_gap is not None:
        # Radix maps gap "0" to a literal 0; there is no --space-0 token.
        classes.append(
            "gap-0" if effective_gap == "0" else f"gap-[var(--space-{effective_gap})]"
        )
    if effective_gap_x is not None:
        classes.append(
            "gap-x-0"
            if effective_gap_x == "0"
            else f"gap-x-[var(--space-{effective_gap_x})]"
        )
    if effective_gap_y is not None:
        classes.append(
            "gap-y-0"
            if effective_gap_y == "0"
            else f"gap-y-[var(--space-{effective_gap_y})]"
        )
    classes.extend([
        ALIGN[align] if align else "items-stretch",
        JUSTIFY[justify] if justify else "justify-start",
    ])
    merge_class_name(" ".join(classes), props)
    return rx.el.div(*children, **props)
