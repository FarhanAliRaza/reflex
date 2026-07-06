"""Radix-parity Inset (side=all, standalone)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name


def inset(*children, **props) -> rx.Component:
    """A Radix-faithful Inset (side=all, standalone).

    Returns:
        The rendered component.
    """
    merge_class_name("box-border overflow-hidden m-0", props)
    return rx.el.div(*children, **props)
