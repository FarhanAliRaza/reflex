"""Var-valued style (rx.color) + breakpoint list inside a pseudo-selector."""

import reflex as rx

ROUTE = "/style_var_and_bp_pseudo"
IDENT = "StyleVarAndBpPseudo"


def build():
    return rx.box(
        "combo",
        background_color=rx.color("accent", 9),
        _hover={"color": ["red", "blue"]},
    )
