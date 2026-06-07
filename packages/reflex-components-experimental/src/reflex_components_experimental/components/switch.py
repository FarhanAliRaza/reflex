"""Radix-parity switch that animates between states like Radix."""

import reflex as rx
from reflex_components_experimental.utils import cn

_SWITCH_SIZES = {
    "1": ("var(--space-4)", "max(var(--radius-1),var(--radius-thumb))"),
    "2": ("calc(var(--space-5)*5/6)", "max(var(--radius-2),var(--radius-thumb))"),
    "3": ("var(--space-5)", "max(var(--radius-2),var(--radius-thumb))"),
}


def switch(
    checked: bool | rx.Var[bool] = False,
    size: str = "2",
    variant: str = "surface",
    **props,
) -> rx.Component:
    """A Radix-faithful switch that animates between states like Radix.

    ``checked`` may be a reactive Var. The track and thumb are persistent
    elements whose ``background-position`` / ``transform`` are driven reactively
    with a matching CSS ``transition``, so the thumb glides instead of snapping.
    Wire it with an event handler, e.g.
    ``rxe.switch(checked=State.on, on_click=State.toggle)``.

    The reactive geometry is set via inline ``style`` rather than Tailwind
    arbitrary classes: stacked arbitrary variant + deeply-nested ``calc()``
    values aren't reliably emitted by the Tailwind v4 JIT.

    Args:
        checked: Whether the switch is on (a bool or a reactive Var).
        size: Radix size ("1"-"3").
        variant: Reserved for parity with Radix; currently unused.
        **props: Extra props; ``class_name`` overrides win via cn.

    Returns:
        The switch element.
    """
    height, radius = _SWITCH_SIZES[size]
    width = f"calc({height}*1.75)"
    thumb_size = f"calc({height} - 1px*2)"
    translate_x = f"calc({width} - {height})"
    track_style = {
        "position": "absolute",
        "inset": "0",
        "borderRadius": radius,
        "backgroundColor": "var(--gray-a3)",
        "backgroundImage": "linear-gradient(to right, var(--accent-track) 40%, transparent 60%)",
        "backgroundRepeat": "no-repeat",
        "backgroundSize": f"calc({width}*2 + {height}) 100%",
        "transition": "background-position 160ms linear, box-shadow 140ms ease-in-out",
        "backgroundPosition": rx.cond(checked, "0%", "100% 0%"),
        "boxShadow": rx.cond(checked, "none", "inset 0 0 0 1px var(--gray-a5)"),
    }
    thumb_style = {
        "position": "absolute",
        "left": "1px",
        "top": "1px",
        "zIndex": "1",
        "width": thumb_size,
        "height": thumb_size,
        "backgroundColor": "white",
        "borderRadius": f"calc({radius} - 1px)",
        "transition": "transform 140ms cubic-bezier(0.45, 0.05, 0.55, 0.95)",
        "transform": rx.cond(checked, f"translateX({translate_x})", "none"),
    }
    root_cls = (
        "relative inline-flex items-center align-top shrink-0 text-start "
        f"h-[{height}] w-[{width}]"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = rx.cond(
        checked, "checked", "unchecked"
    )
    return rx.el.button(
        rx.el.span(style=track_style),
        rx.el.span(style=thumb_style),
        **props,
    )
