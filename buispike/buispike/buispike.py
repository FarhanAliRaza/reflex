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
    for tag, rfn, pfn in [
        ("em", rx.text.em, P.em),
        ("strong", rx.text.strong, P.strong),
        ("quote", rx.text.quote, P.quote),
    ]:
        k = f"inline-{tag}"
        rows.append(_pair(k, rfn("Sample"), pfn("Sample")))
    for v in ["soft", "surface", "outline"]:
        for s in ["1", "2"]:
            k = f"callout-{v}-{s}"
            rows.append(
                _pair(
                    k,
                    rx.callout("Message", size=s, variant=v, color_scheme="violet"),
                    P.callout("Message", size=s, variant=v),
                )
            )
    for s in ["1", "2", "3", "5"]:
        k = f"bq-{s}"
        rows.append(
            _pair(
                k,
                rx.blockquote("Quote", size=s),
                P.blockquote("Quote", size=s),
            )
        )
    for s in ["1", "2"]:
        k = f"card-{s}"
        rows.append(
            _pair(
                k,
                rx.card("Card body", size=s),
                P.card("Card body", size=s),
            )
        )
    for s in ["1", "2", "3", "4"]:
        k = f"avatar-{s}"
        rows.append(
            _pair(k, rx.avatar(fallback="RX", size=s), P.avatar("RX", size=s))
        )
    for s in ["1", "2", "3"]:
        k = f"spinner-{s}"
        rows.append(_pair(k, rx.spinner(size=s), P.spinner(size=s)))
    for s in ["1", "2", "3", "5"]:
        k = f"link-{s}"
        rows.append(
            _pair(k, rx.link("Read more", size=s, color_scheme="violet", href="#"),
                  P.link("Read more", size=s))
        )

    def _row(key, radix_node, mine_node):
        return rx.el.div(
            rx.el.span(key, class_name="w-36 text-xs text-[var(--secondary-11)]"),
            rx.el.div(radix_node, class_name="inline-flex p-1"),
            rx.el.div(mine_node, class_name="inline-flex p-1"),
            class_name="flex items-center gap-10",
        )

    def _tbl(cell):
        return rx.el.table(rx.el.tbody(rx.el.tr(cell)), class_name="border-collapse")

    for s in ["1", "2", "3"]:
        k = f"tbl-head-{s}"
        rows.append(_row(
            k,
            rx.table.root(rx.table.header(rx.table.row(
                rx.table.column_header_cell("H", custom_attrs={"data-testid": f"radix-{k}"}))), size=s),
            _tbl(P.table_header_cell("H", size=s, custom_attrs={"data-testid": f"mine-{k}"})),
        ))
    for s in ["1", "2", "3"]:
        k = f"tbl-cell-{s}"
        rows.append(_row(
            k,
            rx.table.root(rx.table.body(rx.table.row(
                rx.table.cell("C", custom_attrs={"data-testid": f"radix-{k}"}))), size=s),
            _tbl(P.table_cell("C", size=s, custom_attrs={"data-testid": f"mine-{k}"})),
        ))
    rows.append(_row(
        "dl-label",
        rx.data_list.root(rx.data_list.item(
            rx.data_list.label("Name", custom_attrs={"data-testid": "radix-dl-label"}),
            rx.data_list.value("Value"))),
        P.data_list_label("Name", custom_attrs={"data-testid": "mine-dl-label"}),
    ))
    rows.append(_row(
        "dl-value",
        rx.data_list.root(
            rx.data_list.item(rx.data_list.label("A"), rx.data_list.value("V1")),
            rx.data_list.item(
                rx.data_list.label("B"),
                rx.data_list.value("V2", custom_attrs={"data-testid": "radix-dl-value"})),
            rx.data_list.item(rx.data_list.label("C"), rx.data_list.value("V3")),
        ),
        P.data_list_value("V2", custom_attrs={"data-testid": "mine-dl-value"}),
    ))
    for v in ["surface", "soft"]:
        for s in ["1", "2", "3"]:
            rows.append(_pair(
                f"tf-{v}-{s}",
                rx.input(placeholder="Text", size=s, variant=v, color_scheme="violet"),
                P.text_field(placeholder="Text", size=s, variant=v),
            ))
            rows.append(_pair(
                f"ta-{v}-{s}",
                rx.text_area(placeholder="Text", size=s, variant=v, color_scheme="violet", width="200px"),
                P.text_area(placeholder="Text", size=s, variant=v, class_name="w-[200px]"),
            ))
    # Switch / Checkbox / Radio (fixed states; visuals on ::before/::after)
    for s in ["1", "2", "3"]:
        rows.append(_pair(f"switch-on-{s}", rx.switch(size=s, default_checked=True, color_scheme="violet"), P.switch(checked=True, size=s)))
        rows.append(_pair(f"switch-off-{s}", rx.switch(size=s, default_checked=False, color_scheme="violet"), P.switch(checked=False, size=s)))
        rows.append(_pair(f"cb-on-{s}", rx.checkbox(size=s, default_checked=True, color_scheme="violet"), P.checkbox(checked=True, size=s)))
        rows.append(_pair(f"cb-off-{s}", rx.checkbox(size=s, default_checked=False, color_scheme="violet"), P.checkbox(checked=False, size=s)))
        rows.append(_pair(f"radio-on-{s}", rx.radio_group.root(rx.radio_group.item(value="a"), size=s, default_value="a", variant="surface", color_scheme="violet"), P.radio(checked=True, size=s)))
        rows.append(_pair(f"radio-off-{s}", rx.radio_group.root(rx.radio_group.item(value="a"), size=s, default_value="", variant="surface", color_scheme="violet"), P.radio(checked=False, size=s)))
    # Layout primitives
    for g in ["1", "2", "3"]:
        rows.append(_pair(f"flex-gap-{g}", rx.flex(rx.el.span("A"), rx.el.span("B"), spacing=g, direction="row"), P.flex(rx.el.span("A"), rx.el.span("B"), gap=g, direction="row")))
        rows.append(_pair(f"grid-gap-{g}", rx.grid(rx.el.span("A"), rx.el.span("B"), columns="2", spacing=g), P.grid(rx.el.span("A"), rx.el.span("B"), columns="2", gap=g)))
    for s in ["1", "2", "3"]:
        rows.append(_pair(f"section-{s}", rx.section(rx.el.span("X"), size=s), P.section(rx.el.span("X"), size=s)))
    rows.append(_pair("box-1", rx.box(rx.el.span("X"), class_name="w-[80px] h-[40px]"), P.box(rx.el.span("X"), class_name="w-[80px] h-[40px]")))
    # Tabs trigger (active + idle)
    for s in ["1", "2"]:
        for state, act in [("active", True), ("idle", False)]:
            k = f"tabs-{state}-{s}"
            rows.append(_row(
                k,
                rx.tabs.root(rx.tabs.list(
                    rx.tabs.trigger("Tab", value="a", custom_attrs={"data-testid": f"radix-{k}"}),
                    rx.tabs.trigger("Tab", value="b"), size=s),
                    default_value=("a" if act else "b")),
                P.tabs_list(
                    P.tabs_trigger("Tab", size=s, active=act, custom_attrs={"data-testid": f"mine-{k}"}),
                    P.tabs_trigger("Tab", size=s, active=not act), size=s),
            ))
    # Accordion trigger + item
    rows.append(_row(
        "accordion-trigger",
        rx.accordion.root(rx.accordion.item(
            rx.accordion.header(rx.accordion.trigger("Header", custom_attrs={"data-testid": "radix-accordion-trigger"})),
            rx.accordion.content("Content", value="a"), value="a"),
            type="single", default_value="a", collapsible=True, color_scheme="violet", width="300px"),
        P.accordion_trigger("Header", custom_attrs={"data-testid": "mine-accordion-trigger"}, class_name="w-[300px]"),
    ))
    # Select trigger
    rows.append(_row(
        "select-trigger-2",
        rx.select.root(rx.select.trigger(custom_attrs={"data-testid": "radix-select-trigger-2"}),
                       rx.select.content(rx.select.item("a", value="a")), default_value="a", size="2"),
        P.select_trigger("a", size="2", variant="surface", custom_attrs={"data-testid": "mine-select-trigger-2"}),
    ))
    # Overlay content panels (rendered open via default_open/open)
    rows.append(_row(
        "tooltip-content",
        rx.tooltip(rx.button("x"), content="hi", default_open=True, custom_attrs={"data-testid": "radix-tooltip-content"}),
        P.tooltip_content("hi", custom_attrs={"data-testid": "mine-tooltip-content"}),
    ))
    rows.append(_row(
        "popover-content",
        rx.popover.root(rx.popover.trigger(rx.button("x")),
                        rx.popover.content("hi", custom_attrs={"data-testid": "radix-popover-content"}), open=True),
        P.popover_content("hi", custom_attrs={"data-testid": "mine-popover-content"}),
    ))
    rows.append(_row(
        "alertdialog-content",
        rx.alert_dialog.root(rx.alert_dialog.trigger(rx.button("Open")),
                             rx.alert_dialog.content("Body", custom_attrs={"data-testid": "radix-alertdialog-content"}), default_open=True),
        P.alert_dialog_content("Body", custom_attrs={"data-testid": "mine-alertdialog-content"}),
    ))
    rows.append(_row(
        "seg-root-2",
        rx.segmented_control.root(rx.segmented_control.item("One", value="a"), rx.segmented_control.item("Two", value="b"),
                                  size="2", default_value="a", custom_attrs={"data-testid": "radix-seg-root-2"}),
        P.segmented_root(P.segmented_item("One", size="2", active=True), P.segmented_item("Two", size="2"),
                         size="2", custom_attrs={"data-testid": "mine-seg-root-2"}),
    ))
    rows.append(_row(
        "select-content",
        rx.select.root(rx.select.trigger(), rx.select.content(rx.select.item("a", value="a"),
                       custom_attrs={"data-testid": "radix-select-content"}, size="2", variant="solid", position="popper"),
                       default_value="a", size="2", open=True),
        P.select_content(P.select_item("a", size="2"), size="2", custom_attrs={"data-testid": "mine-select-content"}),
    ))
    rows.append(_row(
        "select-item",
        rx.select.root(rx.select.trigger(), rx.select.content(
            rx.select.item("Hi", value="b", custom_attrs={"data-testid": "radix-select-item", "data-highlighted": ""}),
            size="2", variant="solid", position="popper"), default_value="a", size="2", open=True),
        P.select_content(P.select_item("Hi", size="2", highlighted=True, custom_attrs={"data-testid": "mine-select-item"}), size="2"),
    ))
    rows.append(_row(
        "hovercard-content",
        rx.hover_card.root(rx.hover_card.trigger(rx.el.span("x")),
                           rx.hover_card.content("hi", custom_attrs={"data-testid": "radix-hovercard-content"}), default_open=True),
        P.hovercard_content("hi", custom_attrs={"data-testid": "mine-hovercard-content"}),
    ))
    rows.append(_row(
        "dialog-content",
        rx.dialog.root(rx.dialog.trigger(rx.button("Open")),
                       rx.dialog.content("Body", custom_attrs={"data-testid": "radix-dialog-content"}), default_open=True),
        P.dialog_content("Body", custom_attrs={"data-testid": "mine-dialog-content"}),
    ))
    rows.append(_row(
        "menu-content",
        rx.menu.root(rx.menu.trigger(rx.button("Menu")),
                     rx.menu.content(rx.menu.item("Item A"), custom_attrs={"data-testid": "radix-menu-content"}, size="2"), open=True),
        P.menu_content(P.menu_item("Item A"), custom_attrs={"data-testid": "mine-menu-content"}),
    ))
    rows.append(_row(
        "menu-item",
        rx.menu.root(rx.menu.trigger(rx.button("Menu")),
                     rx.menu.content(rx.menu.item("Hi", custom_attrs={"data-testid": "radix-menu-item", "data-highlighted": ""}), size="2"), open=True),
        P.menu_content(P.menu_item("Hi", highlighted=True, custom_attrs={"data-testid": "mine-menu-item"})),
    ))
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
_cmp = __import__("os").environ.get("REFLEX_CMP")
if _cmp in ("parity", "radix"):
    from buispike import cmp as _cmppages
    app.add_page(getattr(_cmppages, f"{_cmp}_page"), route="/")
else:
    app.add_page(index, route="/")
    app.add_page(demo, route="/demo")
