"""Radix-parity heading (mirrors ``.rt-Heading``, default weight bold)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_HEADING_BASE = "font-bold not-italic font-[family-name:var(--heading-font-family)]"


def heading(*children, size: str = "6", **props) -> rx.Component:
    """A Radix-faithful heading.

    Args:
        *children: Content.
        size: "1"-"9".
        **props: Extra props.

    Returns:
        The heading element.
    """
    cls = (
        f"{_HEADING_BASE} "
        f"text-[length:calc(var(--font-size-{size})*var(--heading-font-size-adjust))] "
        f"leading-[var(--heading-line-height-{size})] "
        f"tracking-[calc(var(--letter-spacing-{size})+var(--heading-letter-spacing))]"
    )
    merge_class_name(cls, props)
    return rx.el.h1(*children, **props)
