"""Radix-parity horizontal separator (mirrors ``.rt-Separator``)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SEP_SIZE = {"1": "--space-4", "2": "--space-6", "3": "--space-9"}


def separator(size: str = "1", **props) -> rx.Component:
    """A Radix-faithful horizontal separator.

    Args:
        size: "1"-"3" (width).
        **props: Extra props.

    Returns:
        The separator element.
    """
    cls = f"block bg-[var(--accent-a6)] h-px w-[var({_SEP_SIZE[size]})]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)
