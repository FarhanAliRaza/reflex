"""Radix-parity button (mirrors ``.rt-BaseButton`` / ``.rt-Button``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_BTN_BASE = (
    "inline-flex items-center justify-center shrink-0 align-top box-border "
    "relative select-none font-medium whitespace-nowrap border-0 "
    "cursor-[var(--cursor-button)] bg-transparent"
)

# non-ghost size -> (height, px, gap, font-size idx, radius idx)
_SIZES = {
    "1": ("--space-5", "--space-2", "--space-1", "1", "--radius-1"),
    "2": ("--space-6", "--space-3", "--space-2", "2", "--radius-2"),
    "3": ("--space-7", "--space-4", "--space-3", "3", "--radius-3"),
    "4": ("--space-8", "--space-5", "--space-3", "4", "--radius-4"),
}
# ghost size -> (px, py, gap, font-size idx, radius idx)
_GHOST_SIZES = {
    "1": ("--space-2", "var(--space-1)", "--space-1", "1", "--radius-1"),
    "2": ("--space-2", "var(--space-1)", "--space-1", "2", "--radius-2"),
    "3": ("--space-3", "calc(var(--space-1)*1.5)", "--space-2", "3", "--radius-3"),
    "4": ("--space-4", "var(--space-2)", "--space-2", "4", "--radius-4"),
}

_VARIANT_COLORS = {
    "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)] hover:bg-[var(--accent-10)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)] hover:bg-[var(--accent-a4)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a8)] text-[var(--accent-a11)] hover:bg-[var(--accent-a2)]",
    "surface": "bg-[var(--accent-surface)] shadow-[inset_0_0_0_1px_var(--accent-a7)] text-[var(--accent-a11)]",
    "ghost": "text-[var(--accent-a11)] hover:bg-[var(--accent-a3)]",
}


def _font(fs: str) -> str:
    return (
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})]"
    )


def _classes(size: str, variant: str) -> str:
    if variant == "ghost":
        px, py, gap, fs, rad = _GHOST_SIZES[size]
        box = (
            f"box-content font-normal px-[var({px})] py-[{py}] gap-[var({gap})] "
            f"-mx-[var({px})] -my-[{py}] h-fit "
            f"rounded-[max(var({rad}),var(--radius-full))]"
        )
    else:
        h, px, gap, fs, rad = _SIZES[size]
        box = (
            f"h-[var({h})] px-[var({px})] gap-[var({gap})] "
            f"rounded-[max(var({rad}),var(--radius-full))]"
        )
    return f"{_BTN_BASE} {_font(fs)} {box} {_VARIANT_COLORS[variant]}"


def button(
    *children,
    size: str = "2",
    variant: str = "solid",
    **props,
) -> rx.Component:
    """A Radix-faithful button.

    Args:
        *children: Button content.
        size: Radix size ("1"-"4").
        variant: solid/soft/outline/surface/ghost.
        **props: Extra props; ``class_name`` overrides win via cn.

    Returns:
        The button element.
    """
    merge_class_name(_classes(size, variant), props)
    return rx.el.button(*children, **props)
