"""Radix-parity badge (mirrors ``.rt-Badge``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_BADGE_BASE = (
    "inline-flex items-center shrink-0 whitespace-nowrap font-medium not-italic"
)
_BADGE_SIZES = {
    "1": (
        "text-[length:var(--font-size-1)] leading-[var(--line-height-1)] "
        "tracking-[var(--letter-spacing-1)] "
        "py-[calc(var(--space-1)*0.5)] px-[calc(var(--space-1)*1.5)] "
        "gap-[calc(var(--space-1)*1.5)] rounded-[max(var(--radius-1),var(--radius-full))]"
    ),
    "2": (
        "text-[length:var(--font-size-1)] leading-[var(--line-height-1)] "
        "tracking-[var(--letter-spacing-1)] py-[var(--space-1)] px-[var(--space-2)] "
        "gap-[calc(var(--space-1)*1.5)] rounded-[max(var(--radius-2),var(--radius-full))]"
    ),
    "3": (
        "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
        "tracking-[var(--letter-spacing-2)] py-[var(--space-1)] "
        "px-[calc(var(--space-2)*1.25)] gap-[var(--space-2)] "
        "rounded-[max(var(--radius-2),var(--radius-full))]"
    ),
}
_BADGE_VARIANTS = {
    "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)]",
    "surface": "bg-[var(--accent-surface)] shadow-[inset_0_0_0_1px_var(--accent-a6)] text-[var(--accent-a11)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a8)] text-[var(--accent-a11)]",
}


def badge(*children, size: str = "1", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful badge.

    Args:
        *children: Content.
        size: "1"-"3".
        variant: solid/soft/surface/outline.
        **props: Extra props.

    Returns:
        The badge element.
    """
    cls = f"{_BADGE_BASE} {_BADGE_SIZES[size]} {_BADGE_VARIANTS[variant]}"
    merge_class_name(cls, props)
    return rx.el.span(*children, **props)
