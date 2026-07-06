"""Radix-parity callout (mirrors ``.rt-CalloutRoot``)."""

import reflex as rx
from reflex_components_experimental.typography.text import text
from reflex_components_experimental.utils import merge_class_name

_CALLOUT_BASE = (
    "box-border grid items-start justify-start text-left text-[var(--accent-a11)]"
)
_CALLOUT_SIZES = {
    "1": "gap-y-[var(--space-2)] gap-x-[var(--space-2)] p-[var(--space-3)] rounded-[var(--radius-3)]",
    "2": "gap-y-[var(--space-2)] gap-x-[var(--space-3)] p-[var(--space-4)] rounded-[var(--radius-4)]",
    "3": "gap-y-[var(--space-3)] gap-x-[var(--space-4)] p-[var(--space-5)] rounded-[var(--radius-5)]",
}
_CALLOUT_VARIANTS = {
    "soft": "bg-[var(--accent-a3)]",
    "surface": "shadow-[inset_0_0_0_1px_var(--accent-a6)] bg-[var(--accent-a2)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a7)]",
}


def callout(*children, size: str = "1", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful callout root.

    Args:
        *children: Content.
        size: "1"-"3".
        variant: soft/surface/outline.
        **props: Extra props.

    Returns:
        The callout element.
    """
    cls = f"{_CALLOUT_BASE} {_CALLOUT_SIZES[size]} {_CALLOUT_VARIANTS[variant]}"
    merge_class_name(cls, props)
    # Radix wraps callout content in a Text child (callout 1-2 -> text 2, 3 -> 3).
    return rx.el.div(text(*children, size="3" if size == "3" else "2"), **props)
