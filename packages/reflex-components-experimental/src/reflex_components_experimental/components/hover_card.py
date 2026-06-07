"""Radix-parity hover card content panel (size 2)."""

import reflex as rx
from reflex_components_experimental.utils import cn


def hovercard_content(*children, **props) -> rx.Component:
    """A Radix-faithful hover card content panel (size 2).

    Returns:
        The rendered component.
    """
    cls = (
        "box-border relative overflow-auto p-[var(--space-4)] rounded-[var(--radius-4)] "
        "bg-[var(--color-panel-solid)] shadow-[var(--shadow-4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)
