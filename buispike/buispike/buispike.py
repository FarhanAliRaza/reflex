"""Spike app: Base UI + atomic Tailwind theme, fully working.

Demonstrates: interactive switch (Python state round-trip), default + overridden
buttons (tailwind-merge), a Base UI dialog (headless open/close/focus-trap),
and dark mode via a `.dark` class on <html> (so the portaled dialog is themed).
"""

import reflex as rx

from buispike.bui import button, dialog, switch


class State(rx.State):
    """App state."""

    on: bool = True

    @rx.event
    def set_on(self, value: bool):
        """Set switch state.

        Args:
            value: New checked value.
        """
        self.on = value


_CARD = (
    "flex flex-col gap-6 w-[26rem] p-8 rounded-[calc(var(--radius)+4px)] "
    "border border-[var(--secondary-6)] bg-[var(--secondary-2)]"
)
_ROW = "flex items-center gap-3"
_LABEL = "text-sm text-[var(--secondary-11)]"
_TOGGLE_DARK = rx.call_script("document.documentElement.classList.toggle('dark')")


def index() -> rx.Component:
    """The spike page."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h1(
                    "Base UI + atomic Tailwind",
                    class_name="text-2xl font-bold text-[var(--secondary-12)]",
                ),
                button(
                    "Toggle theme",
                    on_click=_TOGGLE_DARK,
                    class_name="bg-[var(--secondary-12)] text-[var(--secondary-1)] "
                    "hover:bg-[var(--secondary-11)]",
                ),
                class_name="flex items-center justify-between w-full",
            ),
            rx.el.div(
                switch(checked=State.on, on_checked_change=State.set_on),
                rx.el.span(rx.cond(State.on, "On", "Off"), class_name=_LABEL),
                class_name=_ROW,
            ),
            rx.el.div(
                button("Primary"),
                button(
                    "Destructive (override)",
                    class_name="bg-red-600 hover:bg-red-700",
                ),
                class_name=_ROW,
            ),
            dialog.root(
                dialog.trigger("Open dialog"),
                dialog.portal(
                    dialog.backdrop(),
                    dialog.popup(
                        dialog.title("Base UI Dialog"),
                        dialog.description(
                            "Headless behavior, atomic Tailwind styling, "
                            "a fraction of a KB of CSS.",
                        ),
                        rx.el.div(
                            dialog.close("Got it"),
                            class_name="mt-5 flex justify-end",
                        ),
                    ),
                ),
            ),
            class_name=_CARD,
        ),
        class_name="min-h-screen flex items-center justify-center "
        "bg-[var(--secondary-1)] text-[var(--secondary-12)]",
        style={"fontFamily": "system-ui, sans-serif"},
    )


app = rx.App(stylesheets=["theme.css"])
app.add_page(index, route="/")
