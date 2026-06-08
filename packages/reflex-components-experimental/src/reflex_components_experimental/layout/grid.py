"""Radix-parity Grid container."""

import reflex as rx
from reflex_components_experimental.layout.base import ALIGN, JUSTIFY
from reflex_components_experimental.utils import cn


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
        classes.append(f"gap-[var(--space-{gap})]")
    if align:
        classes.append(ALIGN[align])
    if justify:
        classes.append(JUSTIFY[justify])
    props["class_name"] = cn(" ".join(classes), props.pop("class_name", ""))
    return rx.el.div(*children, **props)
