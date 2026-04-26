"""Visual showcase of every converted Radix component.

Each row demonstrates a converted component in all its variants/sizes
so you can verify the in-place rewrite (Tailwind utilities + Radix CSS
variables, no ``@radix-ui/themes`` precompiled CSS) still renders the
familiar look. The Radix accent variables are still in scope through
the ``rx.theme(...)`` config so colors track the theme automatically.

Run::

    cd examples/visual_diff_buttons
    uv run reflex run

Then open http://localhost:3000.
"""

from __future__ import annotations

import reflex as rx

RADIX_VARIANTS: list[str] = ["solid", "soft", "outline", "surface", "ghost", "classic"]
RADIX_SIZES: list[str] = ["1", "2", "3", "4"]
BADGE_VARIANTS: list[str] = ["solid", "soft", "outline", "surface"]
BADGE_SIZES: list[str] = ["1", "2", "3"]
CALLOUT_VARIANTS: list[str] = ["soft", "surface", "outline"]


def _section(title: str, *children) -> rx.Component:
    return rx.box(
        rx.heading(title, size="5", class_name="mb-3"),
        rx.flex(*children, wrap="wrap", spacing="2"),
        class_name="mb-8 rounded-lg border border-[var(--gray-a4)] p-4",
    )


def _label(text: str, *children) -> rx.Component:
    return rx.box(
        *children,
        rx.text(text, size="1", class_name="mt-2 text-[var(--gray-10)] font-mono"),
        class_name="flex flex-col items-start gap-1 p-2",
    )


def buttons_section() -> rx.Component:
    cells: list[rx.Component] = []
    for variant in RADIX_VARIANTS:
        row: list[rx.Component] = []
        for size in RADIX_SIZES:
            row.append(
                _label(
                    f"{variant} sz={size}",
                    rx.button(
                        f"{variant} {size}",
                        variant=variant,  # pyright: ignore[reportArgumentType]
                        size=size,  # pyright: ignore[reportArgumentType]
                    ),
                )
            )
        cells.append(rx.flex(*row, spacing="2", class_name="items-end"))
    return _section("Button (every variant × size)", *cells)


def badges_section() -> rx.Component:
    cells: list[rx.Component] = []
    for variant in BADGE_VARIANTS:
        row: list[rx.Component] = []
        for size in BADGE_SIZES:
            row.append(
                _label(
                    f"{variant} sz={size}",
                    rx.badge(
                        f"{variant} {size}",
                        variant=variant,  # pyright: ignore[reportArgumentType]
                        size=size,  # pyright: ignore[reportArgumentType]
                    ),
                )
            )
        cells.append(rx.flex(*row, spacing="2", class_name="items-end"))
    return _section("Badge (every variant × size)", *cells)


def callouts_section() -> rx.Component:
    cells: list[rx.Component] = []
    for variant in CALLOUT_VARIANTS:
        cells.append(
            _label(
                f"variant={variant}",
                rx.callout(
                    "Heads up — this is a callout message.",
                    icon="info",
                    variant=variant,  # pyright: ignore[reportArgumentType]
                ),
            )
        )
    return _section("Callout", *cells)


def card_section() -> rx.Component:
    cells: list[rx.Component] = []
    for variant in ("surface", "classic", "ghost"):
        cells.append(
            _label(
                f"variant={variant}",
                rx.card(
                    rx.text("Card title", weight="bold"),
                    rx.text("This is some card body text.", size="2"),
                    variant=variant,  # pyright: ignore[reportArgumentType]
                    class_name="w-56",
                ),
            )
        )
    return _section("Card", *cells)


def heading_section() -> rx.Component:
    cells: list[rx.Component] = []
    for size in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        cells.append(
            _label(
                f"size={size}",
                rx.heading(f"Heading {size}", size=size),  # pyright: ignore[reportArgumentType]
            )
        )
    return _section("Heading", *cells)


def text_section() -> rx.Component:
    cells: list[rx.Component] = []
    for size in ("1", "2", "3", "4", "5", "6"):
        cells.append(
            _label(
                f"size={size}",
                rx.text(f"Body text size {size}", size=size),  # pyright: ignore[reportArgumentType]
            )
        )
    cells.append(_label("em", rx.text.em("Emphasis")))
    cells.append(_label("strong", rx.text.strong("Strong")))
    cells.append(_label("kbd 2", rx.text.kbd("⌘K", size="2")))
    cells.append(_label("kbd 3", rx.text.kbd("Esc", size="3")))
    cells.append(_label("quote", rx.text.quote("'A quotation.'")))
    return _section("Text family", *cells)


def link_section() -> rx.Component:
    return _section(
        "Link",
        _label("auto", rx.link("Auto underline", href="#", underline="auto")),
        _label("hover", rx.link("Hover underline", href="#", underline="hover")),
        _label("always", rx.link("Always underline", href="#", underline="always")),
        _label("none", rx.link("No underline", href="#", underline="none")),
    )


def code_section() -> rx.Component:
    cells: list[rx.Component] = []
    for variant in ("solid", "soft", "outline", "ghost"):
        cells.append(
            _label(
                f"variant={variant}",
                rx.code(
                    "rx.theme(accent_color='violet')",
                    variant=variant,  # pyright: ignore[reportArgumentType]
                ),
            )
        )
    return _section("Code", *cells)


def blockquote_section() -> rx.Component:
    return _section(
        "Blockquote",
        rx.blockquote(
            "Reflex is the fastest way to build interactive web apps in Python.",
            size="3",
            class_name="max-w-md",
        ),
    )


def separator_section() -> rx.Component:
    return _section(
        "Separator",
        rx.box(
            rx.text("Above"),
            rx.separator(),
            rx.text("Below"),
            class_name="w-64 space-y-2",
        ),
    )


def spinner_section() -> rx.Component:
    return _section(
        "Spinner",
        _label("size=1", rx.spinner(size="1")),
        _label("size=2", rx.spinner(size="2")),
        _label("size=3", rx.spinner(size="3")),
    )


def skeleton_section() -> rx.Component:
    return _section(
        "Skeleton",
        rx.box(
            rx.skeleton(class_name="h-4 w-48 mb-2"),
            rx.skeleton(class_name="h-4 w-72 mb-2"),
            rx.skeleton(class_name="h-4 w-32"),
        ),
    )


def avatar_section() -> rx.Component:
    cells: list[rx.Component] = []
    for size in ("1", "2", "3", "4", "5", "6"):
        cells.append(
            _label(
                f"size={size}",
                rx.avatar(fallback="RF", size=size),  # pyright: ignore[reportArgumentType]
            )
        )
    return _section("Avatar (fallback only)", *cells)


def icon_button_section() -> rx.Component:
    cells: list[rx.Component] = []
    for size in ("1", "2", "3", "4"):
        for variant in ("solid", "soft", "outline", "ghost"):
            cells.append(
                _label(
                    f"{variant} sz={size}",
                    rx.icon_button(
                        "settings",
                        variant=variant,  # pyright: ignore[reportArgumentType]
                        size=size,  # pyright: ignore[reportArgumentType]
                    ),
                )
            )
    return _section("IconButton", *cells)


def layout_section() -> rx.Component:
    return _section(
        "Layout primitives",
        _label(
            "flex row, spacing=3",
            rx.flex(
                rx.box("A", class_name="bg-[var(--accent-3)] p-2"),
                rx.box("B", class_name="bg-[var(--accent-3)] p-2"),
                rx.box("C", class_name="bg-[var(--accent-3)] p-2"),
                spacing="3",
            ),
        ),
        _label(
            "grid 3-cols, spacing=2",
            rx.grid(
                *[
                    rx.box(str(i), class_name="bg-[var(--accent-3)] p-2 text-center")
                    for i in range(1, 7)
                ],
                columns="3",
                spacing="2",
                class_name="w-48",
            ),
        ),
        _label(
            "container size=2",
            rx.container(
                rx.text("Bounded width content."),
                size="2",
                class_name="bg-[var(--accent-2)]",
            ),
        ),
        _label(
            "section",
            rx.section(rx.text("Section content."), class_name="bg-[var(--accent-2)]"),
        ),
    )


def index() -> rx.Component:
    return rx.container(
        rx.heading("Radix → shadcn-style visual showcase", size="7"),
        rx.text(
            "Every component below renders through the in-place rewritten "
            "reflex-components-radix package. No @radix-ui/themes precompiled "
            "CSS — only Tailwind utilities + Radix CSS variables.",
            class_name="mb-6 text-[var(--gray-11)]",
        ),
        buttons_section(),
        badges_section(),
        callouts_section(),
        card_section(),
        heading_section(),
        text_section(),
        link_section(),
        code_section(),
        blockquote_section(),
        separator_section(),
        spinner_section(),
        skeleton_section(),
        avatar_section(),
        icon_button_section(),
        layout_section(),
        size="4",
        class_name="py-8",
    )


app = rx.App()
app.add_page(index, route="/", title="Radix visual showcase")
