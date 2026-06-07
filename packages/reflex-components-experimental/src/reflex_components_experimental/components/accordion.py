"""Radix-parity (classic) accordion trigger + item."""

import reflex as rx
from reflex_components_experimental.utils import cn


def accordion_trigger(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion trigger box.

    Returns:
        The rendered component.
    """
    cls = (
        "flex flex-1 justify-between items-center w-full m-0 bg-none border-none box-border "
        "px-[var(--space-4)] py-[var(--space-3)] text-[length:1.1em] leading-[1] text-[var(--accent-contrast)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.button(*children, **props)


def accordion_item(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion item box (single/first+last).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "block overflow-hidden w-full box-border m-0 rounded-[var(--radius-4)]",
        props.pop("class_name", ""),
    )
    return rx.el.div(*children, **props)
