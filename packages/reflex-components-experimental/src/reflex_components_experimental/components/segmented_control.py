"""Radix-parity SegmentedControl (Root + Item)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SEG_SIZES = {
    "1": ("1", "--space-5", "--space-3", "1", "2"),
    "2": ("2", "--space-6", "--space-4", "2", "2"),
    "3": ("3", "--space-7", "--space-4", "3", "3"),
}


def segmented_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful SegmentedControl root.

    Returns:
        The rendered component.
    """
    _, h, _px, _gap, rad = _SEG_SIZES[size]
    cls = (
        "inline-grid align-top [grid-auto-flow:column] [grid-auto-columns:1fr] "
        "items-stretch relative isolate text-center not-italic min-w-max "
        "font-[family-name:var(--default-font-family)] text-[var(--gray-12)] "
        "bg-[var(--color-surface)] "
        "[background-image:linear-gradient(var(--gray-a3),var(--gray-a3))] "
        f"h-[var({h})] rounded-[max(var(--radius-{rad}),var(--radius-full))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def segmented_item(
    text: str, size: str = "2", active: bool = False, **props
) -> rx.Component:
    """A Radix-faithful SegmentedControl item.

    Returns:
        The rendered component.
    """
    fs, _h, px, gap, rad = _SEG_SIZES[size]
    before = (
        "before:content-[''] before:absolute before:inset-px before:-z-10 "
        f"before:rounded-[max(0.5px,calc(max(var(--radius-{rad}),var(--radius-full))-1px))] "
        "before:bg-[var(--segmented-control-indicator-background-color)]"
        if active
        else ""
    )
    weight = "font-medium" if active else "font-normal"
    label_cls = (
        "box-border flex grow items-center justify-center relative "
        f"px-[var({px})] gap-[var(--space-{gap})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))] {before}"
    )
    fsz = f"text-[length:var(--font-size-{fs})]"
    # Like Radix: an in-flow medium + (-0.01em) sizing copy fixes the column
    # width so items don't reflow when activated; visible copy overlaid.
    sizing = rx.el.span(
        text, class_name=f"{fsz} font-medium tracking-[-0.01em] invisible"
    )
    vls = "tracking-[-0.01em]" if active else f"tracking-[var(--letter-spacing-{fs})]"
    visible = rx.el.span(
        text,
        class_name=f"{fsz} {weight} {vls} absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    props["class_name"] = cn(
        "flex items-stretch select-none", props.pop("class_name", "")
    )
    return rx.el.div(rx.el.span(sizing, visible, class_name=label_cls), **props)
