"""Radix-parity surface card (mirrors ``.rt-BaseCard`` / ``.rt-Card``).

Background lives on a ``::before`` pseudo and the 1px ring on ``::after``,
exactly like Radix, so the root element itself stays transparent (matching
Radix's root computed styles).
"""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_CARD_BASE = (
    "block relative overflow-hidden box-border not-italic text-start [contain:paint] "
    "font-normal font-[family-name:var(--default-font-family)] "
    "before:content-[''] before:absolute before:inset-0 before:-z-10 "
    "before:bg-[var(--color-panel)] "
    "after:content-[''] after:absolute after:pointer-events-none "
    "after:inset-[var(--card-border-width)] "
    "after:shadow-[var(--base-card-surface-box-shadow)]"
)
# size -> (padding token, radius idx); mirrors .rt-Card's --card-padding /
# --card-border-radius per size.
_CARD_SIZES = {
    "1": ("--space-3", "4"),
    "2": ("--space-4", "4"),
    "3": ("--space-5", "5"),
    "4": ("--space-6", "5"),
    "5": ("--space-8", "6"),
}


def card(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful surface card.

    Args:
        *children: Content.
        size: "1"-"5".
        **props: Extra props.

    Returns:
        The card element.
    """
    pad, rad = _CARD_SIZES[size]
    inner_radius = f"calc(var(--radius-{rad})-var(--card-border-width))"
    cls = (
        f"{_CARD_BASE} p-[var({pad})] rounded-[var(--radius-{rad})] "
        f"before:rounded-[{inner_radius}] after:rounded-[{inner_radius}]"
    )
    merge_class_name(cls, props)
    return rx.el.div(*children, **props)
