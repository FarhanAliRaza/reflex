"""A polished Reflex starter homepage."""

import reflex as rx

from rxconfig import config


class State(rx.State):
    """The app state."""


CARD_STYLE = {
    "background": "rgba(255, 255, 255, 0.78)",
    "backdrop_filter": "blur(14px)",
    "border": "1px solid var(--gray-a5)",
    "border_radius": "24px",
    "box_shadow": "0 18px 60px rgba(15, 23, 42, 0.08)",
}

BUTTON_BASE_STYLE = {
    "display": "inline-flex",
    "align_items": "center",
    "justify_content": "center",
    "border_radius": "999px",
    "font_weight": "600",
    "padding": "0.8rem 1.25rem",
    "text_decoration": "none",
}


def stat_card(value: str, label: str) -> rx.Component:
    return rx.el.div(
        rx.heading(value, size="8", weight="bold"),
        rx.text(label, size="3", color="var(--gray-11)"),
        style={
            **CARD_STYLE,
            "padding": "1.5rem",
        },
    )


def feature_card(title: str, description: str) -> rx.Component:
    return rx.el.div(
        rx.text(
            title,
            style={
                "font_size": "1.1rem",
                "font_weight": "700",
                "margin_bottom": "0.65rem",
            },
        ),
        rx.text(
            description,
            size="3",
            color="var(--gray-11)",
            style={"line_height": "1.7"},
        ),
        style={
            **CARD_STYLE,
            "padding": "1.6rem",
            "height": "100%",
        },
    )


def cta(label: str, href: str, *, primary: bool = False) -> rx.Component:
    return rx.link(
        label,
        href=href,
        is_external=href.startswith("http"),
        style={
            **BUTTON_BASE_STYLE,
            "background": (
                "var(--accent-9)" if primary else "rgba(255, 255, 255, 0.72)"
            ),
            "border": (
                "1px solid transparent" if primary else "1px solid var(--gray-a6)"
            ),
            "color": ("white" if primary else "var(--gray-12)"),
        },
    )


def index() -> rx.Component:
    return rx.el.div(
        rx.color_mode.button(position="top-right"),
        rx.container(
            rx.el.header(
                rx.el.div(
                    rx.text(
                        "Reflex",
                        style={
                            "font_size": "1.15rem",
                            "font_weight": "800",
                            "letter_spacing": "-0.02em",
                        },
                    ),
                    rx.el.div(
                        rx.link(
                            "Docs",
                            href="https://reflex.dev/docs/getting-started/introduction/",
                            is_external=True,
                            color="var(--gray-11)",
                            underline="none",
                        ),
                        rx.link(
                            "Examples",
                            href="https://reflex.dev/docs/gallery/gallery/",
                            is_external=True,
                            color="var(--gray-11)",
                            underline="none",
                        ),
                        style={
                            "display": "flex",
                            "gap": "1.25rem",
                            "align_items": "center",
                        },
                    ),
                    style={
                        "display": "flex",
                        "justify_content": "space-between",
                        "align_items": "center",
                        "padding_top": "1.25rem",
                        "padding_bottom": "1rem",
                    },
                )
            ),
            rx.el.main(
                rx.el.section(
                    rx.el.div(
                        rx.text(
                            "PURE PYTHON FULL-STACK",
                            style={
                                "font_size": "0.82rem",
                                "font_weight": "700",
                                "letter_spacing": "0.16em",
                                "color": "var(--accent-10)",
                                "margin_bottom": "1rem",
                            },
                        ),
                        rx.heading(
                            "Start with a homepage that already feels like a product.",
                            size="9",
                            weight="bold",
                            style={
                                "max_width": "11ch",
                                "line_height": "1.02",
                                "letter_spacing": "-0.04em",
                            },
                        ),
                        rx.text(
                            "This starter app gives you a polished landing page, "
                            "the same Reflex backend state model, and a frontend "
                            "path that can target React or SvelteKit.",
                            size="5",
                            color="var(--gray-11)",
                            style={
                                "max_width": "42rem",
                                "line_height": "1.7",
                                "margin_top": "1.25rem",
                            },
                        ),
                        rx.el.div(
                            cta(
                                "Read the docs",
                                "https://reflex.dev/docs/getting-started/introduction/",
                                primary=True,
                            ),
                            cta(
                                "Browse components",
                                "https://reflex.dev/docs/library/getting-started/",
                            ),
                            style={
                                "display": "flex",
                                "flex_wrap": "wrap",
                                "gap": "0.9rem",
                                "margin_top": "1.75rem",
                            },
                        ),
                        rx.el.div(
                            rx.text(
                                "Start editing",
                                style={
                                    "font_size": "0.85rem",
                                    "font_weight": "700",
                                    "text_transform": "uppercase",
                                    "letter_spacing": "0.08em",
                                    "color": "var(--gray-10)",
                                },
                            ),
                            rx.code(
                                f"{config.app_name}/{config.app_name}.py",
                                style={
                                    "display": "inline-block",
                                    "margin_top": "0.55rem",
                                    "padding": "0.35rem 0.6rem",
                                    "border_radius": "999px",
                                },
                            ),
                            rx.text(
                                "Run `uv run reflex run` to iterate locally and "
                                "`uv run reflex export` to build a shareable frontend.",
                                size="3",
                                color="var(--gray-11)",
                                style={
                                    "margin_top": "0.9rem",
                                    "line_height": "1.7",
                                },
                            ),
                            style={
                                **CARD_STYLE,
                                "margin_top": "2rem",
                                "padding": "1.3rem 1.4rem",
                                "max_width": "34rem",
                            },
                        ),
                        style={
                            **CARD_STYLE,
                            "padding": "2.5rem",
                            "background": (
                                "linear-gradient(135deg, "
                                "rgba(255, 255, 255, 0.92), "
                                "rgba(246, 248, 255, 0.82))"
                            ),
                        },
                    ),
                    style={
                        "padding_top": "2.5rem",
                    },
                ),
                rx.el.section(
                    rx.el.div(
                        stat_card("1 file", "to launch your first polished homepage"),
                        stat_card(
                            "2 targets", "with React by default and SvelteKit opt-in"
                        ),
                        stat_card(
                            "0 rewrites", "for your backend state and event model"
                        ),
                        style={
                            "display": "grid",
                            "grid_template_columns": "repeat(auto-fit, minmax(210px, 1fr))",
                            "gap": "1rem",
                        },
                    ),
                    style={
                        "padding_top": "1.25rem",
                    },
                ),
                rx.el.section(
                    rx.heading(
                        "What you can ship from this starter",
                        size="7",
                        weight="bold",
                        style={"margin_bottom": "0.8rem"},
                    ),
                    rx.text(
                        "Use this page as a real homepage foundation instead of "
                        "replacing a blank screen before you can demo anything.",
                        size="4",
                        color="var(--gray-11)",
                        style={
                            "max_width": "44rem",
                            "line_height": "1.7",
                            "margin_bottom": "1.5rem",
                        },
                    ),
                    rx.el.div(
                        feature_card(
                            "Keep backend semantics stable",
                            "State, events, and server workflows stay the same "
                            "while you iterate on the frontend experience.",
                        ),
                        feature_card(
                            "Switch frontend targets intentionally",
                            "Start on the default React path or opt into the "
                            "new SvelteKit target without changing your app model.",
                        ),
                        feature_card(
                            "Demo something polished on day one",
                            "Hero copy, metrics, and feature sections are already "
                            "here so you can focus on product details next.",
                        ),
                        style={
                            "display": "grid",
                            "grid_template_columns": "repeat(auto-fit, minmax(220px, 1fr))",
                            "gap": "1rem",
                        },
                    ),
                    style={
                        "padding_top": "3rem",
                        "padding_bottom": "4rem",
                    },
                ),
                style={"padding_bottom": "2rem"},
            ),
            rx.el.footer(
                rx.text(
                    "Built with Reflex. Replace this starter content with your "
                    "own product story when you are ready.",
                    size="3",
                    color="var(--gray-11)",
                ),
                style={
                    "padding_bottom": "2rem",
                },
            ),
            size="4",
        ),
        style={
            "min_height": "100vh",
            "background": (
                "radial-gradient(circle at top, "
                "rgba(59, 130, 246, 0.14), "
                "rgba(255, 255, 255, 0) 34%), "
                "linear-gradient(180deg, #f8fbff 0%, #ffffff 52%, #f7f8fc 100%)"
            ),
        },
    )


app = rx.App()
app.add_page(index)
