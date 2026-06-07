"""Radix-parity Container (centered, max-width by size)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_CONTAINER_MAX = {
    "1": "--container-1",
    "2": "--container-2",
    "3": "--container-3",
    "4": "--container-4",
}


def container(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Container.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "flex box-border flex-col items-center shrink-0 grow p-[16px]",
        props.pop("class_name", ""),
    )
    inner = rx.el.div(
        *children, class_name=f"w-full max-w-[var({_CONTAINER_MAX[size]})]"
    )
    return rx.el.div(inner, **props)
