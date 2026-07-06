"""Radix-parity Box layout primitive."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name


def box(*children, **props) -> rx.Component:
    """A Radix-faithful Box.

    Returns:
        The rendered component.
    """
    merge_class_name("block box-border", props)
    return rx.el.div(*children, **props)
