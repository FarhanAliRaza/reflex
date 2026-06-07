"""Radix-parity slider (track + range + thumb, surface variant)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SLIDER_TRACK = {
    "1": "calc(var(--space-2)*0.75)",
    "2": "var(--space-2)",
    "3": "calc(var(--space-2)*1.25)",
}
_SLIDER_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--slider-track-size)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def slider_track(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider track (surface).

    Returns:
        The rendered component.
    """
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] overflow-hidden relative grow h-[{h}] {_SLIDER_RADIUS} "
        "bg-[var(--gray-a3)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def slider_range(size: str = "2", *, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful slider range (surface).

    Returns:
        The rendered component.
    """
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] absolute h-full left-0 w-[{value}%] {_SLIDER_RADIUS} "
        "bg-[var(--accent-track)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


def slider_thumb(size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider thumb (surface).

    Returns:
        The rendered component.
    """
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] block relative outline-0 "
        f"w-[calc({h}+var(--space-1))] h-[calc({h}+var(--space-1))] "
        "after:content-[''] after:absolute after:inset-[calc(-0.25*var(--slider-track-size))] "
        "after:bg-white after:rounded-[max(var(--radius-1),var(--radius-thumb))] "
        "after:shadow-[0_0_0_1px_var(--black-a4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(**props)
