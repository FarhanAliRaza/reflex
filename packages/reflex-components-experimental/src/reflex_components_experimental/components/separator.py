"""Radix-parity horizontal separator (mirrors ``.rt-Separator``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

# Size 4 spans the full container, like .rt-Separator's --separator-size.
_SEP_SIZE = {
    "1": "var(--space-4)",
    "2": "var(--space-6)",
    "3": "var(--space-9)",
    "4": "100%",
}


def separator(size: str = "1", **props) -> rx.Component:
    """A Radix-faithful horizontal separator.

    Args:
        size: "1"-"4" (width).
        **props: Extra props.

    Returns:
        The separator element.
    """
    cls = f"block bg-[var(--accent-a6)] h-px w-[{_SEP_SIZE[size]}]"
    merge_class_name(cls, props)
    return rx.el.div(**props)
