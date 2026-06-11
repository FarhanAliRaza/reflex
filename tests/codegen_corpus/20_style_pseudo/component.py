"""Pseudo-selector props (_hover, nested _before) + a `:focus` style-dict key."""

import reflex as rx

ROUTE = "/style_pseudo"
IDENT = "StylePseudo"


def build():
    return rx.box(
        "hover me",
        _hover={"color": "red", "_before": {"content": '"*"'}},
        style={":focus": {"outline": "none"}},
    )
