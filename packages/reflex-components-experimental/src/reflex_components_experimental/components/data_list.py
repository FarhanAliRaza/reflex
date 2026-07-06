"""Radix-parity DataList label / value (horizontal layout)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_DL_FONT = (
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
    "tracking-[var(--letter-spacing-2)] font-normal not-italic "
    "font-[family-name:var(--default-font-family)] text-start"
)


def data_list_label(*children, **props) -> rx.Component:
    """A Radix-faithful DataList label.

    Returns:
        The rendered component.
    """
    cls = f"flex min-w-[120px] text-[var(--gray-a11)] {_DL_FONT}"
    merge_class_name(cls, props)
    return rx.el.div(*children, **props)


def data_list_value(*children, **props) -> rx.Component:
    """A Radix-faithful DataList value (non-edge horizontal item).

    Returns:
        The rendered component.
    """
    cls = f"flex min-w-0 mx-0 my-[-0.25em] text-[var(--gray-12)] {_DL_FONT}"
    merge_class_name(cls, props)
    return rx.el.dd(*children, **props)
