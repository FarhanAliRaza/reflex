"""Radix-parity link (accent color, auto underline)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_LINK_DECORATION = (
    "[text-decoration-line:none] [text-decoration-style:solid] "
    "[text-decoration-thickness:min(2px,max(1px,0.05em))] "
    "[text-underline-offset:calc(0.025em_+_2px)] "
    "[text-decoration-color:color-mix(in_oklab,var(--accent-a5),var(--gray-a6))]"
)


def link(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful link (accent color, auto underline).

    Returns:
        The rendered component.
    """
    cls = (
        f"text-[var(--accent-a11)] text-start "
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] font-normal not-italic "
        f"font-[family-name:var(--default-font-family)] {_LINK_DECORATION}"
    )
    merge_class_name(cls, props)
    props.setdefault("href", "#")
    return rx.el.a(*children, **props)
