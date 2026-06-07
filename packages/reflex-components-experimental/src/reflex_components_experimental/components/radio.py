"""Radix-parity single radio item (fixed checked/unchecked state)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_RADIO_SIZES = {
    "1": "calc(var(--space-4)*0.875)",
    "2": "var(--space-4)",
    "3": "calc(var(--space-4)*1.25)",
}


def radio(
    checked: bool = False, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful single radio item in a fixed state.

    Returns:
        The rendered component.
    """
    rsize = _RADIO_SIZES[size]
    state = "checked" if checked else "unchecked"
    if checked:
        before_bg = "before:bg-[var(--accent-indicator)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
        after_cls = (
            "after:content-[''] after:pointer-events-none after:absolute "
            f"after:w-[{rsize}] after:h-[{rsize}] after:[border-radius:100%] "
            "after:scale-[0.4] after:bg-[var(--accent-contrast)]"
        )
    else:
        before_bg = "before:bg-[var(--color-surface)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
        after_cls = ""
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        f"h-[{rsize}] before:content-[''] before:block "
        f"before:w-[{rsize}] before:h-[{rsize}] before:[border-radius:100%] {before_bg} {after_cls}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(**props)
