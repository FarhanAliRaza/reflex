"""Radix-parity surface card (mirrors ``.rt-BaseCard`` / ``.rt-Card``).

Background lives on a ``::before`` pseudo and the 1px ring on ``::after``,
exactly like Radix, so the root element itself stays transparent (matching
Radix's root computed styles).
"""

import reflex as rx
from reflex_components_experimental.utils import cn

_CARD_BASE = (
    "block relative overflow-hidden box-border not-italic text-start [contain:paint] "
    "font-normal font-[family-name:var(--default-font-family)] "
    "before:content-[''] before:absolute before:inset-0 before:-z-10 "
    "before:rounded-[calc(var(--radius-4)-var(--card-border-width))] "
    "before:bg-[var(--color-panel)] "
    "after:content-[''] after:absolute after:pointer-events-none "
    "after:inset-[var(--card-border-width)] "
    "after:rounded-[calc(var(--radius-4)-var(--card-border-width))] "
    "after:shadow-[var(--base-card-surface-box-shadow)]"
)
_CARD_SIZES = {
    "1": "p-[var(--space-3)] rounded-[var(--radius-4)]",
    "2": "p-[var(--space-4)] rounded-[var(--radius-4)]",
}


def card(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful surface card.

    Args:
        *children: Content.
        size: "1"-"2".
        **props: Extra props.

    Returns:
        The card element.
    """
    cls = f"{_CARD_BASE} {_CARD_SIZES[size]}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)
