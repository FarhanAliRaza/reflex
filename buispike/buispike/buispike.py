"""Spike app: compare a Radix Themes page vs a Base UI + atomic-CSS page.

Two routes so one Vite build emits a per-route CSS chunk for each:
  /radix   - Radix Themes components (rx.switch, rx.button) -> Radix runtime CSS
  /baseui  - Base UI switch + plain HTML layout -> only the atomic CSS module
"""

import reflex as rx

from buispike.baseui_switch import switch as baseui_switch


class State(rx.State):
    """App state."""

    on: bool = True

    @rx.event
    def toggle(self, value: bool):
        """Toggle the switch.

        Args:
            value: The new checked value.
        """
        self.on = value


def radix_page() -> rx.Component:
    """Radix Themes page."""
    return rx.center(
        rx.vstack(
            rx.heading("Radix Themes"),
            rx.switch(default_checked=True),
            rx.button("Action"),
            spacing="4",
            align="center",
        ),
        height="100vh",
    )


def baseui_page() -> rx.Component:
    """Base UI + atomic-CSS page (no Radix layout components)."""
    return rx.el.div(
        rx.el.div(
            rx.el.h1("Base UI + atomic CSS"),
            baseui_switch(
                checked=State.on,
                on_checked_change=State.toggle,
            ),
            style={
                "display": "flex",
                "flexDirection": "column",
                "gap": "16px",
                "alignItems": "center",
            },
        ),
        style={
            "display": "flex",
            "justifyContent": "center",
            "alignItems": "center",
            "height": "100vh",
            "fontFamily": "system-ui, sans-serif",
        },
    )


app = rx.App()
# End-state build: ONLY the Base UI + atomic-CSS page, zero Radix components.
app.add_page(baseui_page, route="/baseui")
