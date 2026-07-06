"""Radix-parity Skeleton (pulsing placeholder)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name


def skeleton(*children, **props) -> rx.Component:
    """A Radix-faithful Skeleton.

    Returns:
        The rendered component.
    """
    cls = (
        "box-border [border-radius:var(--radius-1)] [background-image:none] [border:none] "
        "[box-shadow:none] text-transparent [outline:none] pointer-events-none select-none [background-clip:border-box] "
        "[animation:rt-skeleton-pulse_1000ms_infinite_alternate-reverse]"
    )
    merge_class_name(cls, props)
    return rx.el.span(*children, **props)
