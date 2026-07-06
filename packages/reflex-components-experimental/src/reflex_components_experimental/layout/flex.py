"""Radix-parity Flex container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, FLEX_DIR, JUSTIFY
from reflex_components_experimental.utils import merge_class_name


def flex(
    *children,
    direction: str | None = None,
    gap: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Flex container.

    Returns:
        The rendered component.
    """
    classes = ["flex box-border justify-start"]
    if direction:
        classes.append(FLEX_DIR[direction])
    if gap is not None:
        # Radix maps gap "0" to a literal 0; there is no --space-0 token.
        classes.append("gap-0" if gap == "0" else f"gap-[var(--space-{gap})]")
    if align:
        classes.append(ALIGN[align])
    if justify:
        classes.append(JUSTIFY[justify])
    merge_class_name(" ".join(classes), props)
    return rx.el.div(*children, **props)
