"""Radix-parity text span (mirrors ``.rt-Text``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_TEXT_WEIGHT = {"light": "300", "regular": "400", "medium": "500", "bold": "700"}


def text(*children, size: str = "3", weight: str = "regular", **props) -> rx.Component:
    """A Radix-faithful text span.

    Args:
        *children: Content.
        size: "1"-"9".
        weight: light/regular/medium/bold.
        **props: Extra props.

    Returns:
        The text element.
    """
    cls = (
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] font-[{_TEXT_WEIGHT[weight]}]"
    )
    merge_class_name(cls, props)
    return rx.el.span(*children, **props)
