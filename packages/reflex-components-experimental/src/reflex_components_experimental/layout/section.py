"""Radix-parity Section (vertical padding by size)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_SECTION_PY = {"1": "--space-5", "2": "--space-7", "3": "--space-9"}


def section(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Section.

    Returns:
        The rendered component.
    """
    merge_class_name(f"box-border shrink-0 py-[var({_SECTION_PY[size]})]", props)
    return rx.el.section(*children, **props)
