"""Radix-parity blockquote (mirrors ``.rt-Blockquote``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_BQ_BASE = (
    "box-border "
    "[border-left:max(var(--space-1),0.25em)_solid_var(--accent-a6)] "
    "pl-[min(var(--space-5),max(var(--space-3),0.5em))]"
)


def blockquote(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful blockquote.

    Args:
        *children: Content.
        size: "1"-"9" (text sizing).
        **props: Extra props.

    Returns:
        The blockquote element.
    """
    cls = (
        f"{_BQ_BASE} text-[length:var(--font-size-{size})] "
        f"leading-[var(--line-height-{size})] tracking-[var(--letter-spacing-{size})]"
    )
    merge_class_name(cls, props)
    return rx.el.blockquote(*children, **props)
