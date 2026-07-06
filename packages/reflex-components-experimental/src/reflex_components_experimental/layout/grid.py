"""Radix-parity Grid container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, JUSTIFY
from reflex_components_experimental.utils import merge_class_name


def grid(
    *children,
    columns: str | None = None,
    gap: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Grid container.

    Returns:
        The rendered component.
    """
    classes = [
        "grid box-border items-stretch justify-start",
        "[grid-template-rows:none]",
    ]
    if columns and columns != "1":
        classes.append(f"[grid-template-columns:repeat({columns},minmax(0,1fr))]")
    else:
        classes.append("[grid-template-columns:minmax(0,1fr)]")
    if gap is not None:
        # Radix maps gap "0" to a literal 0; there is no --space-0 token.
        classes.append("gap-0" if gap == "0" else f"gap-[var(--space-{gap})]")
    if align:
        classes.append(ALIGN[align])
    if justify:
        classes.append(JUSTIFY[justify])
    merge_class_name(" ".join(classes), props)
    return rx.el.div(*children, **props)
