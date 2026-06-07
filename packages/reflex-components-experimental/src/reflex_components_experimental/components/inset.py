"""Radix-parity Inset (side=all, standalone)."""

import reflex as rx
from reflex_components_experimental.utils import cn


def inset(*children, **props) -> rx.Component:
    """A Radix-faithful Inset (side=all, standalone).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "box-border overflow-hidden m-0", props.pop("class_name", "")
    )
    return rx.el.div(*children, **props)
