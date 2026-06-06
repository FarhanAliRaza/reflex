"""Parity harness: Radix Themes vs Base UI + atomic Tailwind, side by side.

The index page renders, for each (variant, size), a Radix component and the
parity component in tagged cells so ``diff.py`` can screenshot each and compute
a pixel-diff. A `/demo` page keeps the original interactive showcase.
"""

import reflex as rx

from buispike.bui import button as demo_button
from buispike.bui import dialog, switch
from buispike.parity import button as pbutton

_VARIANTS = ["solid", "soft", "outline", "surface", "ghost"]
_SIZES = ["1", "2", "3", "4"]


def _cell(content, tid: str) -> rx.Component:
    return rx.el.div(
        content,
        custom_attrs={"data-testid": tid},
        class_name="inline-flex p-1",
    )


def index() -> rx.Component:
    """Parity harness page."""
    rows = []
    for variant in _VARIANTS:
        for size in _SIZES:
            key = f"{variant}-{size}"
            rows.append(
                rx.el.div(
                    rx.el.span(
                        key, class_name="w-28 text-xs text-[var(--secondary-11)]"
                    ),
                    _cell(
                        rx.button(
                            "Button",
                            size=size,
                            variant=variant,
                            color_scheme="violet",
                        ),
                        f"radix-{key}",
                    ),
                    _cell(pbutton("Button", size=size, variant=variant), f"mine-{key}"),
                    class_name="flex items-center gap-10",
                )
            )
    return rx.theme(
        rx.el.div(
            rx.el.div("Radix → | ← Base UI", class_name="text-sm font-bold mb-2"),
            *rows,
            class_name="flex flex-col gap-2 p-8 bg-white",
        ),
        accent_color="violet",
        gray_color="slate",
        radius="medium",
    )


class State(rx.State):
    """Demo state."""

    on: bool = True

    @rx.event
    def set_on(self, value: bool):
        """Set switch state.

        Args:
            value: New value.
        """
        self.on = value


def demo() -> rx.Component:
    """Original interactive demo (switch/dialog/buttons/dark mode)."""
    return rx.el.div(
        rx.el.div(
            switch(checked=State.on, on_checked_change=State.set_on),
            demo_button("Primary"),
            demo_button("Override", class_name="bg-red-600 hover:bg-red-700"),
            dialog.root(
                dialog.trigger("Open dialog"),
                dialog.portal(
                    dialog.backdrop(),
                    dialog.popup(
                        dialog.title("Base UI Dialog"),
                        dialog.description("Atomic Tailwind, tiny CSS."),
                        rx.el.div(
                            dialog.close("Got it"),
                            class_name="mt-5 flex justify-end",
                        ),
                    ),
                ),
            ),
            class_name="flex items-center gap-3 p-8",
        ),
        class_name="min-h-screen bg-[var(--secondary-1)] text-[var(--secondary-12)]",
    )


app = rx.App(stylesheets=["theme.css"])
app.add_page(index, route="/")
app.add_page(demo, route="/demo")
