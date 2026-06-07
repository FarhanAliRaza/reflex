"""Radix-parity Box layout primitive."""

import reflex as rx
from reflex_components_experimental.utils import cn


def box(*children, **props) -> rx.Component:
    """A Radix-faithful Box.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn("block box-border", props.pop("class_name", ""))
    return rx.el.div(*children, **props)
