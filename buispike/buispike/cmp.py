"""Same page built two ways for a like-for-like comparison.

`parity_page` uses the Base UI + atomic-Tailwind parity components (only plain
HTML elements + tokens from theme.css). `radix_page` uses the equivalent Radix
Themes components. Selected at build time via the REFLEX_CMP env var so each
build ships only one page's CSS.
"""

import reflex as rx

from buispike import parity as P


# --- Parity (Base UI + atomic Tailwind) -------------------------------------
def _p_row(label: str, checked: bool) -> rx.Component:
    return rx.el.div(
        P.text(label, size="2"),
        P.switch(checked=checked, size="2"),
        class_name="flex items-center justify-between",
    )


def parity_page() -> rx.Component:
    """Settings card built with parity components."""
    return rx.el.div(
        P.card(
            rx.el.div(
                rx.el.div(
                    P.heading("Notifications", size="4"),
                    P.badge("Beta", size="1", variant="soft"),
                    class_name="flex items-center justify-between",
                ),
                P.text(
                    "Manage how you receive notifications.",
                    size="2",
                    class_name="text-[var(--secondary-11)]",
                ),
                P.separator(size="3", class_name="w-full"),
                _p_row("Email", True),
                _p_row("Push", False),
                _p_row("SMS", True),
                rx.el.div(
                    P.button("Cancel", variant="soft"),
                    P.button("Save", variant="solid"),
                    class_name="flex justify-end gap-3 pt-1",
                ),
                class_name="flex flex-col gap-4 w-[22rem]",
            ),
            size="2",
        ),
        class_name="min-h-screen flex items-center justify-center bg-[var(--secondary-1)]",
        style={"fontFamily": "var(--default-font-family)"},
    )


# --- Radix Themes -----------------------------------------------------------
def _r_row(label: str, checked: bool) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2"),
        rx.switch(default_checked=checked, size="2"),
        justify="between",
        width="100%",
    )


def radix_page() -> rx.Component:
    """The same settings card built with Radix Themes components."""
    return rx.theme(
        rx.center(
            rx.card(
                rx.vstack(
                    rx.hstack(
                        rx.heading("Notifications", size="4"),
                        rx.badge("Beta", size="1", variant="soft"),
                        justify="between",
                        width="100%",
                    ),
                    rx.text(
                        "Manage how you receive notifications.",
                        size="2",
                        color_scheme="gray",
                    ),
                    rx.divider(size="4"),
                    _r_row("Email", True),
                    _r_row("Push", False),
                    _r_row("SMS", True),
                    rx.hstack(
                        rx.button("Cancel", variant="soft"),
                        rx.button("Save", variant="solid"),
                        justify="end",
                        width="100%",
                        spacing="3",
                    ),
                    spacing="4",
                    width="22rem",
                ),
                size="2",
            ),
            height="100vh",
        ),
        accent_color="violet",
        gray_color="slate",
        radius="medium",
    )
