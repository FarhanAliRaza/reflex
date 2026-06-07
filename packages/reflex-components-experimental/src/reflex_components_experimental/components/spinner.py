"""Radix-parity spinner root (mirrors ``.rt-Spinner``; leaves are children)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SPINNER_SIZE = {
    "1": "var(--space-3)",
    "2": "var(--space-4)",
    "3": "calc(1.25*var(--space-4))",
}


def spinner(size: str = "2", **props) -> rx.Component:
    """A Radix-faithful spinner root.

    Args:
        size: "1"-"3".
        **props: Extra props.

    Returns:
        The spinner element.
    """
    sz = _SPINNER_SIZE[size]
    cls = f"block relative opacity-[var(--spinner-opacity)] w-[{sz}] h-[{sz}]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(**props)
