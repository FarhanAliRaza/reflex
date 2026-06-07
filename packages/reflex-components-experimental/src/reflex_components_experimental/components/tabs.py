"""Radix-parity tabs (``TabsList`` + ``TabsTrigger``)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_TABS_SIZES = {
    "1": ("1", "--space-6", "--space-1", "--space-1", "calc(var(--space-1)*0.5)", "1"),
    "2": ("2", "--space-7", "--space-2", "--space-2", "var(--space-1)", "2"),
}


def tabs_list(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful TabsList.

    Returns:
        The rendered component.
    """
    fs, *_ = _TABS_SIZES[size]
    cls = (
        "flex justify-start overflow-x-auto whitespace-nowrap not-italic "
        "font-[family-name:var(--default-font-family)] "
        "shadow-[inset_0_-1px_0_0_var(--gray-a5)] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def tabs_trigger(
    text: str, size: str = "2", active: bool = False, **props
) -> rx.Component:
    """A Radix-faithful TabsTrigger.

    Returns:
        The rendered component.
    """
    _fs, h, px, ipx, ipy, irad = _TABS_SIZES[size]
    color = "text-[var(--gray-12)]" if active else "text-[var(--gray-a11)]"
    before = (
        "before:content-[''] before:box-border before:absolute before:h-0.5 "
        "before:bottom-0 before:left-0 before:right-0 before:bg-[var(--accent-indicator)]"
        if active
        else ""
    )
    trigger_cls = (
        "flex items-center justify-center shrink-0 relative select-none box-border text-start "
        f"h-[var({h})] px-[var({px})] {color} {before}"
    )
    weight = "font-medium" if active else ""
    base_inner = (
        "flex items-center justify-center box-border "
        f"py-[{ipy}] px-[var({ipx})] rounded-[var(--radius-{irad})]"
    )
    # Like Radix: an in-flow medium-weight sizing copy drives the width (so the
    # tab doesn't reflow when activated), with the visible copy overlaid.
    # active/medium copies carry --tab-active-letter-spacing (-0.01em), which
    # tightens them; the sizing copy is always medium so width is stable.
    act_ls = "tracking-[-0.01em]" if active else ""
    sizing = rx.el.span(
        text, class_name=f"{base_inner} font-medium tracking-[-0.01em] invisible"
    )
    visible = rx.el.span(
        text,
        class_name=f"{base_inner} {weight} {act_ls} absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    props["class_name"] = cn(trigger_cls, props.pop("class_name", ""))
    return rx.el.button(sizing, visible, **props)
