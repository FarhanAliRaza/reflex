"""Parity harness: Radix Themes vs Base UI + atomic Tailwind, side by side.

The index page renders, for each (variant, size), a Radix component and the
parity component in tagged cells so ``diff.py`` can screenshot each and compute
a pixel-diff. A `/demo` page keeps the original interactive showcase.
"""

import reflex as rx

from buispike import parity as P
from buispike.bui import button as demo_button
from buispike.bui import dialog, switch

_BTN_V = ["solid", "soft", "outline", "surface", "ghost"]
_BADGE_V = ["solid", "soft", "surface", "outline"]
_TEXT_SIZES = ["1", "2", "3", "5", "9"]
_TEXT_WEIGHTS = ["regular", "medium", "bold"]


def _cell(content, tid: str) -> rx.Component:
    return rx.el.div(content, custom_attrs={"data-testid": tid}, class_name="inline-flex p-1")


def _pair(key: str, radix_node, mine_node) -> rx.Component:
    return rx.el.div(
        rx.el.span(key, class_name="w-36 text-xs text-[var(--secondary-11)]"),
        _cell(radix_node, f"radix-{key}"),
        _cell(mine_node, f"mine-{key}"),
        class_name="flex items-center gap-10",
    )


def _build_rows():
    rows = []
    for v in _BTN_V:
        for s in ["1", "2", "3", "4"]:
            k = f"btn-{v}-{s}"
            rows.append(
                _pair(
                    k,
                    rx.button("Button", size=s, variant=v, color_scheme="violet"),
                    P.button("Button", size=s, variant=v),
                )
            )
    for v in _BADGE_V:
        for s in ["1", "2", "3"]:
            k = f"badge-{v}-{s}"
            rows.append(
                _pair(
                    k,
                    rx.badge("New", size=s, variant=v, color_scheme="violet"),
                    P.badge("New", size=s, variant=v),
                )
            )
    for s in ["1", "2", "3"]:
        k = f"sep-{s}"
        rows.append(
            _pair(
                k,
                rx.divider(size=s, orientation="horizontal", color_scheme="violet"),
                P.separator(size=s),
            )
        )
    for s in _TEXT_SIZES:
        for w in _TEXT_WEIGHTS:
            k = f"text-{s}-{w}"
            rows.append(
                _pair(
                    k,
                    rx.text("Sample", size=s, weight=w),
                    P.text("Sample", size=s, weight=w),
                )
            )
    for s in ["1", "2", "4", "6", "9"]:
        k = f"head-{s}"
        rows.append(_pair(k, rx.heading("Title", size=s), P.heading("Title", size=s)))
    for v in ["soft", "solid", "outline"]:
        for s in ["1", "2", "3"]:
            k = f"code-{v}-{s}"
            rows.append(
                _pair(
                    k,
                    rx.code("code", size=s, variant=v, color_scheme="violet"),
                    P.code("code", size=s, variant=v),
                )
            )
    return rows


def index() -> rx.Component:
    """Parity harness page (Radix vs parity components)."""
    return rx.theme(
        rx.el.div(
            rx.el.div("Radix → | ← parity", class_name="text-sm font-bold mb-2"),
            *_build_rows(),
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
