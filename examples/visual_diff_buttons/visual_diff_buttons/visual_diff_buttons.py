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


def form_section() -> rx.Component:
    return _section(
        "Form controls",
        _label("checkbox", rx.checkbox("Subscribe to newsletter")),
        _label("switch sm", rx.switch(size="1")),
        _label("switch md", rx.switch(size="2", default_checked=True)),
        _label("switch lg", rx.switch(size="3")),
        _label("radio group", rx.radio(["Apple", "Banana", "Cherry"], default_value="Banana")),
        _label("progress 30%", rx.box(rx.progress(value=30), class_name="w-48")),
        _label("progress 75%", rx.box(rx.progress(value=75, size="3"), class_name="w-48")),
        _label("text_field", rx.text_field(placeholder="Type here...")),
        _label("text_area", rx.text_area(placeholder="Multiline...", rows="3")),
    )


def aspect_ratio_section() -> rx.Component:
    return _section(
        "AspectRatio",
        _label(
            "ratio=16/9",
            rx.box(
                rx.aspect_ratio(
                    rx.box(class_name="size-full bg-[var(--accent-4)] rounded"),
                    ratio=16 / 9,
                ),
                class_name="w-64",
            ),
        ),
        _label(
            "ratio=1",
            rx.box(
                rx.aspect_ratio(
                    rx.box(class_name="size-full bg-[var(--accent-4)] rounded"),
                    ratio=1,
                ),
                class_name="w-32",
            ),
        ),
    )


def inset_section() -> rx.Component:
    return _section(
        "Inset (inside Card)",
        rx.card(
            rx.inset(
                rx.box(class_name="h-24 bg-[var(--accent-5)]"),
                side="top",
                pb="current",
            ),
            rx.text("Card body sitting under the inset image.", size="2", class_name="pt-3"),
            class_name="w-72",
        ),
    )


def scroll_area_section() -> rx.Component:
    return _section(
        "ScrollArea (300×120, vertical)",
        rx.scroll_area(
            rx.flex(
                *[
                    rx.text(f"Line {i + 1}: scrollable content goes here.", size="2")
                    for i in range(20)
                ],
                direction="column",
                spacing="1",
                class_name="p-3",
            ),
            type="auto",
            scrollbars="vertical",
            class_name="h-32 w-72 rounded border border-[var(--gray-a4)]",
        ),
    )


def select_section() -> rx.Component:
    return _section(
        "Select",
        _label(
            "default",
            rx.select(["Apple", "Banana", "Cherry"], default_value="Apple"),
        ),
        _label(
            "with placeholder",
            rx.select(["Red", "Green", "Blue"], placeholder="Pick a color..."),
        ),
        _label(
            "size=3",
            rx.select(["small", "medium", "large"], default_value="medium", size="3"),
        ),
    )


def slider_section() -> rx.Component:
    cells: list[rx.Component] = [_label(f"size={s}", rx.slider(size=s)) for s in ("1", "2", "3")]
    cells.append(_label("default_value=70", rx.slider(default_value=[70])))
    cells.append(_label("with min/max", rx.slider(min=0, max=200, step=10, default_value=[80])))
    return _section("Slider", *cells)


def segmented_control_section() -> rx.Component:
    return _section(
        "SegmentedControl",
        _label(
            "default",
            rx.segmented_control.root(
                rx.segmented_control.item("Inbox", value="inbox"),
                rx.segmented_control.item("Drafts", value="drafts"),
                rx.segmented_control.item("Sent", value="sent"),
                default_value="inbox",
            ),
        ),
        _label(
            "size=2",
            rx.segmented_control.root(
                rx.segmented_control.item("Day", value="day"),
                rx.segmented_control.item("Week", value="week"),
                rx.segmented_control.item("Month", value="month"),
                default_value="week",
                size="2",
            ),
        ),
    )


def radio_cards_section() -> rx.Component:
    return _section(
        "RadioCards",
        rx.radio_cards.root(
            rx.radio_cards.item(
                rx.flex(
                    rx.text("8 GB / 4 CPU", weight="bold"),
                    rx.text("$200 / month", size="2"),
                    direction="column",
                ),
                value="1",
            ),
            rx.radio_cards.item(
                rx.flex(
                    rx.text("16 GB / 8 CPU", weight="bold"),
                    rx.text("$400 / month", size="2"),
                    direction="column",
                ),
                value="2",
            ),
            rx.radio_cards.item(
                rx.flex(
                    rx.text("32 GB / 16 CPU", weight="bold"),
                    rx.text("$800 / month", size="2"),
                    direction="column",
                ),
                value="3",
            ),
            default_value="2",
            columns="3",
            class_name="max-w-xl",
        ),
    )


def radio_group_section() -> rx.Component:
    return _section(
        "RadioGroup (manual)",
        rx.radio_group.root(
            rx.flex(
                rx.text(rx.flex(rx.radio_group.item(value="1"), "Default", spacing="2", class_name="items-center")),
                rx.text(rx.flex(rx.radio_group.item(value="2"), "Comfortable", spacing="2", class_name="items-center")),
                rx.text(rx.flex(rx.radio_group.item(value="3"), "Compact", spacing="2", class_name="items-center")),
                direction="column",
                spacing="2",
            ),
            default_value="1",
        ),
    )


def checkbox_cards_section() -> rx.Component:
    return _section(
        "CheckboxCards",
        rx.checkbox_cards.root(
            rx.checkbox_cards.item("A1 Keyboard", value="kbd"),
            rx.checkbox_cards.item("Mouse", value="mouse"),
            rx.checkbox_cards.item("Monitor", value="monitor"),
            default_value=["mouse"],
            columns="3",
            class_name="max-w-xl",
        ),
    )


def checkbox_group_section() -> rx.Component:
    return _section(
        "CheckboxGroup",
        rx.checkbox_group.root(
            rx.flex(
                rx.text(rx.flex(rx.checkbox_group.item(value="news"), "Newsletter", spacing="2", class_name="items-center")),
                rx.text(rx.flex(rx.checkbox_group.item(value="prom"), "Promotions", spacing="2", class_name="items-center")),
                rx.text(rx.flex(rx.checkbox_group.item(value="prod"), "Product updates", spacing="2", class_name="items-center")),
                direction="column",
                spacing="2",
            ),
            default_value=["prod"],
        ),
    )


def data_list_section() -> rx.Component:
    return _section(
        "DataList",
        rx.data_list.root(
            rx.data_list.item(
                rx.data_list.label("Status"),
                rx.data_list.value(rx.badge("Authorized", variant="soft")),
            ),
            rx.data_list.item(
                rx.data_list.label("ID"),
                rx.data_list.value(rx.code("u_2J89JSA4GJ")),
            ),
            rx.data_list.item(
                rx.data_list.label("Name"),
                rx.data_list.value("Vlad Moroz"),
            ),
            rx.data_list.item(
                rx.data_list.label("Email"),
                rx.data_list.value(rx.link("vlad@workos.com", href="mailto:vlad@workos.com")),
            ),
            class_name="max-w-md",
        ),
    )


def table_section() -> rx.Component:
    return _section(
        "Table",
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Full name"),
                    rx.table.column_header_cell("Email"),
                    rx.table.column_header_cell("Group"),
                ),
            ),
            rx.table.body(
                rx.table.row(
                    rx.table.row_header_cell("Danilo Sousa"),
                    rx.table.cell("danilo@example.com"),
                    rx.table.cell("Developer"),
                ),
                rx.table.row(
                    rx.table.row_header_cell("Zahra Ambessa"),
                    rx.table.cell("zahra@example.com"),
                    rx.table.cell("Admin"),
                ),
                rx.table.row(
                    rx.table.row_header_cell("Jasper Eriksson"),
                    rx.table.cell("jasper@example.com"),
                    rx.table.cell("Developer"),
                ),
            ),
            variant="surface",
            class_name="max-w-2xl",
        ),
    )


def tabs_section() -> rx.Component:
    return _section(
        "Tabs",
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("Account", value="account"),
                rx.tabs.trigger("Documents", value="documents"),
                rx.tabs.trigger("Settings", value="settings"),
            ),
            rx.tabs.content(rx.text("Make changes to your account."), value="account"),
            rx.tabs.content(rx.text("Access and update your documents."), value="documents"),
            rx.tabs.content(rx.text("Edit your project settings."), value="settings"),
            default_value="account",
            class_name="max-w-md",
        ),
    )


def tooltip_section() -> rx.Component:
    return _section(
        "Tooltip (hover the buttons)",
        _label("with content", rx.tooltip(rx.button("Hover me"), content="A helpful tooltip")),
        _label("delay=600", rx.tooltip(rx.button("Slow"), content="Delayed tooltip", delay_duration=600)),
    )


def hover_card_section() -> rx.Component:
    return _section(
        "HoverCard (hover the link)",
        rx.hover_card.root(
            rx.hover_card.trigger(rx.link("@reflex_dev", href="#")),
            rx.hover_card.content(
                rx.flex(
                    rx.heading("Reflex", size="3"),
                    rx.text("The fastest way to build interactive web apps in pure Python.", size="2"),
                    direction="column",
                    spacing="1",
                ),
                class_name="max-w-xs",
            ),
        ),
    )


def popover_section() -> rx.Component:
    return _section(
        "Popover (click)",
        rx.popover.root(
            rx.popover.trigger(rx.button("Open popover")),
            rx.popover.content(
                rx.flex(
                    rx.text("Comment", weight="bold"),
                    rx.text_area(placeholder="Write a comment...", rows="3"),
                    rx.flex(rx.button("Post", size="1"), spacing="2", class_name="justify-end"),
                    direction="column",
                    spacing="2",
                ),
                class_name="w-72",
            ),
        ),
    )


def dialog_section() -> rx.Component:
    return _section(
        "Dialog (click to open)",
        rx.dialog.root(
            rx.dialog.trigger(rx.button("Edit profile")),
            rx.dialog.content(
                rx.dialog.title("Edit profile"),
                rx.dialog.description("Make changes to your profile."),
                rx.flex(
                    rx.text_field(placeholder="Full name", default_value="Freja Johnsen"),
                    rx.text_field(placeholder="Email", default_value="freja@example.com"),
                    direction="column",
                    spacing="3",
                    class_name="mt-4",
                ),
                rx.flex(
                    rx.dialog.close(rx.button("Cancel", variant="soft")),
                    rx.dialog.close(rx.button("Save")),
                    spacing="3",
                    class_name="mt-4 justify-end",
                ),
                size="2",
            ),
        ),
    )


def alert_dialog_section() -> rx.Component:
    return _section(
        "AlertDialog (click to open)",
        rx.alert_dialog.root(
            rx.alert_dialog.trigger(rx.button("Revoke access")),
            rx.alert_dialog.content(
                rx.alert_dialog.title("Revoke access"),
                rx.alert_dialog.description("Are you sure? This application will no longer be accessible."),
                rx.flex(
                    rx.alert_dialog.cancel(rx.button("Cancel", variant="soft")),
                    rx.alert_dialog.action(rx.button("Revoke")),
                    spacing="3",
                    class_name="mt-4 justify-end",
                ),
                size="2",
            ),
        ),
    )


def dropdown_menu_section() -> rx.Component:
    return _section(
        "DropdownMenu (click)",
        rx.dropdown_menu.root(
            rx.dropdown_menu.trigger(rx.button("Options")),
            rx.dropdown_menu.content(
                rx.dropdown_menu.item("Edit"),
                rx.dropdown_menu.item("Duplicate"),
                rx.dropdown_menu.separator(),
                rx.dropdown_menu.item("Archive"),
                rx.dropdown_menu.separator(),
                rx.dropdown_menu.item("Delete"),
            ),
        ),
    )


def context_menu_section() -> rx.Component:
    return _section(
        "ContextMenu (right-click the box)",
        rx.context_menu.root(
            rx.context_menu.trigger(
                rx.box(
                    rx.text("Right-click anywhere in this box.", size="2"),
                    class_name="h-24 w-72 grid place-items-center bg-[var(--accent-2)] rounded border border-dashed border-[var(--accent-a6)]",
                ),
            ),
            rx.context_menu.content(
                rx.context_menu.item("Cut"),
                rx.context_menu.item("Copy"),
                rx.context_menu.item("Paste"),
                rx.context_menu.separator(),
                rx.context_menu.item("Delete"),
            ),
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
        form_section(),
        select_section(),
        slider_section(),
        segmented_control_section(),
        radio_cards_section(),
        radio_group_section(),
        checkbox_cards_section(),
        checkbox_group_section(),
        data_list_section(),
        table_section(),
        tabs_section(),
        tooltip_section(),
        hover_card_section(),
        popover_section(),
        dialog_section(),
        alert_dialog_section(),
        dropdown_menu_section(),
        context_menu_section(),
        aspect_ratio_section(),
        inset_section(),
        scroll_area_section(),
        layout_section(),
        size="4",
        class_name="py-8",
    )


app = rx.App()
app.add_page(index, route="/", title="Radix visual showcase")
