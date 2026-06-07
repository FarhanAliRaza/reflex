"""Radix-parity Skeleton (pulsing placeholder)."""

import reflex as rx
from reflex_components_experimental.utils import cn


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
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)
