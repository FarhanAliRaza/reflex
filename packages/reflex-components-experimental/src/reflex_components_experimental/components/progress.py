"""Radix-parity progress (track root + indicator, surface variant)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_PROGRESS_HEIGHT = {
    "1": "var(--space-1)",
    "2": "calc(var(--space-2)*0.75)",
    "3": "var(--space-2)",
}
_PROGRESS_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--progress-height)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def progress_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful progress track root (surface).

    Returns:
        The rendered component.
    """
    h = _PROGRESS_HEIGHT[size]
    cls = (
        f"[--progress-height:{h}] relative overflow-hidden grow h-[{h}] {_PROGRESS_RADIUS} "
        "bg-[var(--gray-a3)] after:content-[''] after:absolute after:inset-0 "
        "after:rounded-[inherit] after:shadow-[inset_0_0_0_1px_var(--gray-a4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def progress_indicator(*, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful progress indicator (surface).

    Returns:
        The rendered component.
    """
    cls = f"block h-full w-full origin-[left_center] [transform:scaleX(calc({value}/100))] bg-[var(--accent-track)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)
