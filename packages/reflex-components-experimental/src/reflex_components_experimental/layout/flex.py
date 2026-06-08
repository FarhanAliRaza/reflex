"""Radix-parity Flex container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, FLEX_DIR, JUSTIFY
from reflex_components_experimental.utils import cn


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
        classes.append(f"gap-[var(--space-{gap})]")
    if align:
        classes.append(ALIGN[align])
    if justify:
        classes.append(JUSTIFY[justify])
    props["class_name"] = cn(" ".join(classes), props.pop("class_name", ""))
    return rx.el.div(*children, **props)
