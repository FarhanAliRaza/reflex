"""Two equivalent 'sites' for comparison: one built with Radix Themes, one with
the Base UI + atomic-Tailwind parity components.

Same layout + content both ways. Selected at build time via REFLEX_CMP so each
production build ships only one site's CSS:
  REFLEX_CMP=parity  -> parity_page   (plain HTML + theme.css tokens, no Radix)
  REFLEX_CMP=radix   -> radix_page    (Radix Themes components)
"""

import reflex as rx

import reflex_components_experimental as rxe
from buispike import parity as P


# --- Package-driven page (proves reflex_components_experimental + its plugin) -
def pkg_page() -> rx.Component:
    """A page built entirely from the published package (rxe.*).

    The token theme is delivered by ``ExperimentalThemePlugin`` (no manual
    stylesheet), proving the package works end-to-end through the real plugin.
    """
    return rx.el.div(
        rxe.card(
            rx.el.div(
                rx.el.div(
                    rxe.heading("From the package", size="6"),
                    rxe.badge("experimental", size="1", variant="soft"),
                    class_name="flex items-center justify-between gap-4",
                ),
                rxe.text("Rendered with reflex_components_experimental; theme shipped "
                         "by ExperimentalThemePlugin.", size="3",
                         class_name="mt-2 text-[var(--secondary-11)]"),
                rxe.separator(size="3", class_name="w-full my-4"),
                rx.el.div(rxe.text("Notifications", size="2"), rxe.switch(checked=True, size="2"),
                          class_name="flex items-center justify-between"),
                rx.el.div(rxe.button("Save", variant="solid"), rxe.button("Cancel", variant="soft"),
                          class_name="flex gap-3 mt-5 justify-end"),
                class_name="flex flex-col w-[26rem]",
            ), size="2",
        ),
        class_name="min-h-screen flex items-center justify-center bg-[var(--secondary-1)] text-[var(--secondary-12)]",
        style={"fontFamily": "var(--default-font-family)"},
    )


def _row(label, control):
    return rx.el.div(
        rxe.text(label, size="2"),
        control,
        class_name="flex items-center justify-between gap-6 py-2",
    )


def a11y_page() -> rx.Component:
    """Exercises the accessible interactive layer (Base UI behavior).

    Overlays default to open so an axe-core sweep sees their popups in the DOM.
    """
    import reflex_components_experimental as rxe2

    it = rxe2

    return rx.el.div(
        rxe.heading("Accessible interactive components", size="6"),
        rxe.text(
            "Every control below is backed by Base UI headless behavior.",
            size="2",
            class_name="text-[var(--secondary-11)]",
        ),
        rxe.separator(size="3", class_name="w-full my-4"),
        _row("Switch", it.switch(size="2", default_checked=True)),
        _row("Checkbox", it.checkbox(size="2", default_checked=True)),
        _row(
            "Radio group",
            it.radio_group(
                rx.el.label(
                    it.radio("a"), rxe.text("Option A", size="2"),
                    class_name="flex items-center gap-2",
                ),
                rx.el.label(
                    it.radio("b"), rxe.text("Option B", size="2"),
                    class_name="flex items-center gap-2",
                ),
                default_value="a",
                class_name="flex-row gap-6",
            ),
        ),
        _row("Slider", rx.el.div(it.slider(default_value=40), class_name="w-48")),
        _row("Progress", rx.el.div(it.progress(value=60), class_name="w-48")),
        _row(
            "Segmented",
            it.segmented_control.root(
                it.segmented_control.item("Day", "day"),
                it.segmented_control.item("Week", "week"),
                default_value=["day"],
            ),
        ),
        it.tabs.root(
            it.tabs.list(
                it.tabs.tab("Account", "account"),
                it.tabs.tab("Settings", "settings"),
            ),
            it.tabs.panel(
                rxe.text("Account panel", size="2"), value="account",
                class_name="py-3",
            ),
            it.tabs.panel(
                rxe.text("Settings panel", size="2"), value="settings",
                class_name="py-3",
            ),
            default_value="account",
            class_name="mt-4 w-full",
        ),
        it.accordion.root(
            it.accordion.item(
                it.accordion.trigger(
                    rxe.text("What is this?", size="2"),
                    class_name="bg-[var(--accent-9)]",
                ),
                it.accordion.panel(
                    rxe.text("An accessible accordion.", size="2"),
                    class_name="text-[var(--gray-12)]",
                ),
                value="one",
                class_name="bg-[var(--color-panel-solid)] shadow-[inset_0_0_0_1px_var(--gray-a5)]",
            ),
            default_value=["one"],
            class_name="mt-4 w-full",
        ),
        # Open overlays so axe can audit their popups.
        it.dialog.root(
            it.dialog.trigger("Open dialog", class_name="mt-4 self-start"),
            it.dialog.portal(
                it.dialog.backdrop(),
                it.dialog.popup(
                    it.dialog.title("Dialog title"),
                    it.dialog.description("An accessible, focus-trapped dialog."),
                    it.dialog.close("Close", class_name="mt-4"),
                ),
            ),
            default_open=True,
        ),
        it.popover.root(
            it.popover.trigger("Popover"),
            it.popover.portal(
                it.popover.positioner(
                    it.popover.popup(rxe.text("Popover body", size="2")),
                    side_offset=8,
                )
            ),
        ),
        it.menu.root(
            it.menu.trigger("Menu"),
            it.menu.portal(
                it.menu.positioner(
                    it.menu.popup(
                        it.menu.item("Profile"),
                        it.menu.item("Settings"),
                        it.menu.item("Log out"),
                    ),
                    side_offset=8,
                )
            ),
        ),
        it.select.root(
            it.select.trigger(it.select.value(placeholder="Pick one")),
            it.select.portal(
                it.select.positioner(
                    it.select.popup(
                        it.select.item(it.select.item_text("Apple"), value="apple"),
                        it.select.item(it.select.item_text("Banana"), value="banana"),
                    ),
                    side_offset=8,
                )
            ),
            default_value="apple",
        ),
        class_name="min-h-screen flex flex-col items-stretch gap-1 max-w-[34rem] mx-auto px-6 py-10 "
        "bg-[var(--secondary-1)] text-[var(--secondary-12)]",
        style={"fontFamily": "var(--default-font-family)"},
    )


_FEATURES = [
    ("Fast", "Single-digit-KB CSS per page, shipped only where used.", "New"),
    ("Faithful", "Pixel-matched to the design system you already use.", "Stable"),
    ("Flexible", "Override any component with your own Tailwind classes.", "Beta"),
]
_ROWS = [("Starter", "$0", "Free"), ("Pro", "$19", "Popular"), ("Team", "$49", "")]
_TOGGLES = [("Email digest", True), ("Product updates", False), ("Security alerts", True)]


# --- Parity (Base UI + atomic Tailwind) -------------------------------------
def _p_nav():
    return rx.el.div(
        rx.el.div(P.heading("Acme", size="4"), P.badge("v2", size="1", variant="soft"),
                  class_name="flex items-center gap-3"),
        rx.el.div(P.button("Docs", variant="ghost"), P.button("Pricing", variant="ghost"),
                  P.button("Sign up", variant="solid"), class_name="flex items-center gap-2"),
        class_name="flex items-center justify-between w-full",
    )


def _p_hero():
    return rx.el.div(
        P.badge("Now in public beta", size="2", variant="soft"),
        P.heading("Ship the look, not the bytes", size="9", class_name="mt-3 max-w-[40rem]"),
        P.text("A component layer that matches your design system pixel-for-pixel "
               "while shipping a fraction of the CSS.", size="4",
               class_name="mt-3 max-w-[34rem] text-[var(--secondary-11)]"),
        rx.el.div(P.button("Get started", size="3", variant="solid"),
                  P.button("Read the RFC", size="3", variant="soft"),
                  class_name="flex gap-3 mt-6"),
        class_name="flex flex-col items-center text-center py-16",
    )


def _p_feature(title, body, tag):
    return P.card(
        rx.el.div(
            rx.el.div(P.heading(title, size="4"), P.badge(tag, size="1", variant="soft"),
                      class_name="flex items-center justify-between"),
            P.text(body, size="2", class_name="mt-2 text-[var(--secondary-11)]"),
            class_name="flex flex-col",
        ), size="2",
    )


def _p_toggle(label, checked):
    return rx.el.div(P.text(label, size="2"), P.switch(checked=checked, size="2"),
                     class_name="flex items-center justify-between")


def _p_table():
    head = rx.el.tr(*[P.table_header_cell(h, size="2") for h in ("Plan", "Price", "")])
    body = [rx.el.tr(P.table_cell(n, size="2"), P.table_cell(pr, size="2"),
            P.table_cell(P.badge(t, size="1", variant="soft") if t else "", size="2"))
            for n, pr, t in _ROWS]
    return rx.el.table(rx.el.thead(head), rx.el.tbody(*body), class_name="border-collapse w-full")


def parity_page() -> rx.Component:
    """Landing 'site' built with parity components."""
    return rx.el.div(
        rx.el.div(
            _p_nav(),
            _p_hero(),
            rx.el.div(*[_p_feature(*f) for f in _FEATURES],
                      class_name="grid grid-cols-3 gap-4"),
            rx.el.div(
                P.card(rx.el.div(P.heading("Notifications", size="4"),
                                 *[_p_toggle(l, c) for l, c in _TOGGLES],
                                 class_name="flex flex-col gap-4"), size="2"),
                P.card(_p_table(), size="2"),
                class_name="grid grid-cols-2 gap-4 mt-4",
            ),
            P.callout("Heads up — these components ship ~7x less CSS than the originals.",
                      size="2", variant="surface", class_name="mt-4"),
            P.separator(size="3", class_name="w-full mt-10"),
            P.text("© Acme — built with Base UI + atomic Tailwind", size="1",
                   class_name="block text-center mt-4 text-[var(--secondary-11)]"),
            class_name="max-w-[64rem] mx-auto px-6 py-8",
        ),
        class_name="min-h-screen bg-[var(--secondary-1)] text-[var(--secondary-12)]",
        style={"fontFamily": "var(--default-font-family)"},
    )


# --- Radix Themes -----------------------------------------------------------
def _r_feature(title, body, tag):
    return rx.card(rx.vstack(
        rx.hstack(rx.heading(title, size="4"), rx.badge(tag, size="1", variant="soft"),
                  justify="between", width="100%"),
        rx.text(body, size="2", color_scheme="gray"), spacing="2", width="100%"), size="2")


def radix_page() -> rx.Component:
    """The same 'site' built with Radix Themes components."""
    return rx.theme(
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.hstack(rx.heading("Acme", size="4"), rx.badge("v2", size="1", variant="soft"), spacing="3", align="center"),
                    rx.hstack(rx.button("Docs", variant="ghost"), rx.button("Pricing", variant="ghost"),
                              rx.button("Sign up", variant="solid"), spacing="2", align="center"),
                    justify="between", width="100%",
                ),
                rx.vstack(
                    rx.badge("Now in public beta", size="2", variant="soft"),
                    rx.heading("Ship the look, not the bytes", size="9", align="center", style={"maxWidth": "40rem"}),
                    rx.text("A component layer that matches your design system pixel-for-pixel "
                            "while shipping a fraction of the CSS.", size="4", align="center",
                            color_scheme="gray", style={"maxWidth": "34rem"}),
                    rx.hstack(rx.button("Get started", size="3", variant="solid"),
                              rx.button("Read the RFC", size="3", variant="soft"), spacing="3"),
                    align="center", spacing="3", padding_y="64px",
                ),
                rx.grid(*[_r_feature(*f) for f in _FEATURES], columns="3", spacing="4", width="100%"),
                rx.grid(
                    rx.card(rx.vstack(rx.heading("Notifications", size="4"),
                            *[rx.hstack(rx.text(l, size="2"), rx.switch(default_checked=c, size="2"),
                              justify="between", width="100%") for l, c in _TOGGLES],
                            spacing="4", width="100%"), size="2"),
                    rx.card(rx.table.root(
                        rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in ("Plan", "Price", "")])),
                        rx.table.body(*[rx.table.row(rx.table.cell(n), rx.table.cell(pr),
                            rx.table.cell(rx.badge(t, size="1", variant="soft") if t else "")) for n, pr, t in _ROWS]),
                        size="2", width="100%"), size="2"),
                    columns="2", spacing="4", width="100%",
                ),
                rx.callout("Heads up — these components ship ~7x less CSS than the originals.",
                           size="2", variant="surface", width="100%"),
                rx.divider(size="4"),
                rx.text("© Acme — built with Radix Themes", size="1", align="center", color_scheme="gray"),
                spacing="4", width="100%", style={"maxWidth": "64rem"}, margin="0 auto", padding="32px 24px",
            ),
            min_height="100vh",
        ),
        accent_color="violet", gray_color="slate", radius="medium",
    )
