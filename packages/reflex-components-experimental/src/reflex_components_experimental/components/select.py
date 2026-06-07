"""Radix-parity select (trigger + content panel + item)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SELECT_TRIGGER_BASE = (
    "inline-flex items-center justify-between shrink-0 select-none align-top box-border "
    "font-[family-name:var(--default-font-family)] font-[var(--font-weight-regular)] not-italic "
    "text-start text-[var(--gray-12)]"
)
_SELECT_TRIGGER_SIZES = {
    "1": ("--space-5", "--space-2", "var(--space-1)", "1", "--radius-1"),
    "2": ("--space-6", "--space-3", "calc(var(--space-1)*1.5)", "2", "--radius-2"),
    "3": ("--space-7", "--space-4", "var(--space-2)", "3", "--radius-3"),
}
_SELECT_TRIGGER_VARIANTS = {
    "surface": "bg-[var(--color-surface)] text-[var(--gray-12)] shadow-[inset_0_0_0_1px_var(--gray-a7)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-12)]",
}


def select_trigger(
    text: str, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful select trigger button.

    Returns:
        The rendered component.
    """
    h, px, gap, fs, rad = _SELECT_TRIGGER_SIZES[size]
    cls = (
        f"{_SELECT_TRIGGER_BASE} h-[var({h})] pl-[var({px})] pr-[var({px})] gap-[{gap}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[max(var({rad}),var(--radius-full))] "
        f"{_SELECT_TRIGGER_VARIANTS[variant]}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    chevron = rx.el.span(
        class_name="w-[9px] h-[9px] shrink-0"
    )  # matches .rt-SelectIcon width
    return rx.el.button(rx.el.span(text), chevron, **props)


_SELECT_CONTENT = "flex flex-col overflow-hidden box-border bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)]"
_SELECT_CONTENT_SIZES = {
    "1": ("--space-1", "--radius-3"),
    "2": ("--space-2", "--radius-4"),
    "3": ("--space-2", "--radius-4"),
}
_SELECT_ITEM_SIZES = {
    "1": ("--space-5", "calc(var(--space-5)/1.2)", "1", "--radius-1"),
    "2": ("--space-6", "var(--space-5)", "2", "--radius-2"),
    "3": ("--space-6", "var(--space-5)", "3", "--radius-2"),
}


def select_content(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful select content panel (solid).

    Returns:
        The rendered component.
    """
    pad, rad = _SELECT_CONTENT_SIZES[size]
    props["class_name"] = cn(
        f"{_SELECT_CONTENT} rounded-[var({rad})]", props.pop("class_name", "")
    )
    return rx.el.div(
        rx.el.div(*children, class_name=f"flex flex-col p-[var({pad})]"), **props
    )


def select_item(
    text: str,
    size: str = "2",
    variant: str = "solid",
    highlighted: bool = False,
    **props,
) -> rx.Component:
    """A Radix-faithful select item.

    Returns:
        The rendered component.
    """
    h, padx, fs, rad = _SELECT_ITEM_SIZES[size]
    cls = (
        "flex items-center box-border relative outline-none select-none "
        f"h-[var({h})] pl-[{padx}] pr-[{padx}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[var({rad})]"
    )
    if highlighted:
        cls += (
            " bg-[var(--accent-9)] text-[var(--accent-contrast)]"
            if variant == "solid"
            else " bg-[var(--accent-a4)]"
        )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(rx.el.span(text), **props)
