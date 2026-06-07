"""Radix-parity checkbox (fixed checked/unchecked state)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_CHECKBOX_SIZES = {
    "1": ("calc(var(--space-4)*0.875)", "calc(var(--radius-1)*0.875)"),
    "2": ("var(--space-4)", "var(--radius-1)"),
    "3": ("calc(var(--space-4)*1.25)", "calc(var(--radius-1)*1.25)"),
}


def checkbox(
    checked: bool = False, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful checkbox in a fixed state.

    Returns:
        The rendered component.
    """
    csize, radius = _CHECKBOX_SIZES[size]
    state = "checked" if checked else "unchecked"
    before_bg = (
        "before:bg-[var(--accent-indicator)]"
        if checked
        else "before:bg-[var(--color-surface)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
    )
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] h-[var(--line-height-{size})] "
        f"before:content-[''] before:block "
        f"before:w-[{csize}] before:h-[{csize}] before:rounded-[{radius}] {before_bg}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(**props)
