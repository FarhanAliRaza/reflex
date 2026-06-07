"""Radix-parity scroll area (vertical scrollbar + thumb)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SCROLLBAR_SIZE = {"1": "var(--space-1)", "2": "var(--space-2)", "3": "var(--space-3)"}


def scroll_area_scrollbar(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful vertical scrollbar.

    Returns:
        The rendered component.
    """
    w = _SCROLLBAR_SIZE[size]
    cls = f"flex flex-col select-none w-[{w}] bg-[var(--gray-a3)] rounded-[max(var(--radius-1),var(--radius-full))]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def scroll_area_thumb(**props) -> rx.Component:
    """A Radix-faithful scrollbar thumb.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "relative grow rounded-[inherit] bg-[var(--gray-a8)]",
        props.pop("class_name", ""),
    )
    return rx.el.div(**props)
