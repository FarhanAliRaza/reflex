"""Radix-parity tooltip content panel."""

import reflex as rx
from reflex_components_experimental.utils import cn


def tooltip_content(*children, **props) -> rx.Component:
    """A Radix-faithful tooltip content panel (inner text is size-1; panel font inherits).

    Returns:
        The rendered component.
    """
    cls = "box-border relative py-[var(--space-1)] px-[var(--space-2)] bg-[var(--gray-12)] rounded-[var(--radius-2)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    # Block inner (like Radix's <p class=rt-Text size-1>) so the panel's strut
    # doesn't inflate the height; panel keeps inherited font-size/line-height.
    inner = rx.el.p(
        *children,
        class_name="m-0 text-[length:var(--font-size-1)] leading-[var(--line-height-1)]",
    )
    return rx.el.div(inner, **props)
