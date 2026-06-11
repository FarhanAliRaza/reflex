"""List-valued style props -> responsive media queries (format_as_emotion breakpoints path)."""

import reflex as rx

ROUTE = "/style_breakpoints"
IDENT = "StyleBreakpoints"


def build():
    return rx.box(
        rx.text("responsive", font_size=["1em", "2em", "3em"]),
        width=["100%", "50%", "25%"],
        padding=["4px", "8px"],
    )
