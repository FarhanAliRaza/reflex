"""Radix-parity inline formatting: ``em`` / ``strong`` / ``quote``."""

from collections.abc import Callable

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_LS = "var(--letter-spacing,var(--default-letter-spacing))"


def _inline(
    tag_fn: Callable[..., rx.Component],
    prefix: str,
    *children,
    line_height: str | None = None,
    **props,
) -> rx.Component:
    cls = (
        f"font-[family-name:var(--{prefix}-font-family)] "
        f"text-[length:calc(var(--{prefix}-font-size-adjust)*1em)] "
        f"[font-style:var(--{prefix}-font-style)] [font-weight:var(--{prefix}-font-weight)] "
        f"tracking-[calc(var(--{prefix}-letter-spacing)+{_LS})]"
    )
    if line_height:
        cls += f" box-border leading-[{line_height}]"
    merge_class_name(cls, props)
    return tag_fn(*children, **props)


def em(*children, **props) -> rx.Component:
    """Radix-faithful emphasis (italic).

    Returns:
        The rendered component.
    """
    return _inline(rx.el.em, "em", *children, line_height="1.25", **props)


def strong(*children, **props) -> rx.Component:
    """Radix-faithful strong (bold).

    Returns:
        The rendered component.
    """
    return _inline(rx.el.strong, "strong", *children, **props)


def quote(*children, **props) -> rx.Component:
    """Radix-faithful inline quote.

    Returns:
        The rendered component.
    """
    return _inline(rx.el.q, "quote", *children, line_height="1.25", **props)
