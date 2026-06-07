"""Experimental Reflex components — Base UI + atomic Tailwind, Radix-parity.

Status: experimental. API may change.

Usage::

    import reflex as rx
    import reflex_components_experimental as rxe

    # rxconfig.py: plugins=[rx.plugins.TailwindV4Plugin(), rxe.ExperimentalThemePlugin()]

    def index():
        return rxe.card(
            rxe.heading("Hello", size="6"),
            rxe.text("Tiny CSS, Radix look.", size="3"),
            rxe.button("Go", variant="solid"),
            size="2",
        )

Simple components are top-level callables (``rxe.button``, ``rxe.card``, …);
compound families are grouped namespaces (``rxe.table.cell``, ``rxe.tabs.trigger``,
``rxe.menu.item``, ``rxe.slider.track``, …). The implementations live under the
``components``, ``layout`` and ``typography`` subpackages.
"""

from __future__ import annotations

from types import SimpleNamespace

from reflex_components_experimental.components import (
    accordion_item,
    accordion_trigger,
    alert_dialog_content,
    avatar,
    badge,
    button,
    callout,
    card,
    checkbox,
    data_list_label,
    data_list_value,
    dialog_content,
    hovercard_content,
    inset,
    menu_content,
    menu_item,
    popover_content,
    progress_indicator,
    progress_root,
    radio,
    scroll_area_scrollbar,
    scroll_area_thumb,
    segmented_item,
    segmented_root,
    select_content,
    select_item,
    select_trigger,
    separator,
    skeleton,
    slider_range,
    slider_thumb,
    slider_track,
    spinner,
    switch,
    table_cell,
    table_header_cell,
    tabs_list,
    tabs_trigger,
    text_area,
    text_field,
    tooltip_content,
)
from reflex_components_experimental.layout import box, container, flex, grid, section
from reflex_components_experimental.plugin import ExperimentalThemePlugin
from reflex_components_experimental.typography import (
    blockquote,
    code,
    em,
    heading,
    link,
    quote,
    strong,
    text,
)
from reflex_components_experimental.utils import cn

# --- compound families ------------------------------------------------------
table = SimpleNamespace(cell=table_cell, header_cell=table_header_cell)
data_list = SimpleNamespace(label=data_list_label, value=data_list_value)
tabs = SimpleNamespace(list=tabs_list, trigger=tabs_trigger)
segmented_control = SimpleNamespace(root=segmented_root, item=segmented_item)
slider = SimpleNamespace(track=slider_track, range=slider_range, thumb=slider_thumb)
progress = SimpleNamespace(root=progress_root, indicator=progress_indicator)
scroll_area = SimpleNamespace(scrollbar=scroll_area_scrollbar, thumb=scroll_area_thumb)
tooltip = SimpleNamespace(content=tooltip_content)
popover = SimpleNamespace(content=popover_content)
hover_card = SimpleNamespace(content=hovercard_content)
dialog = SimpleNamespace(content=dialog_content)
alert_dialog = SimpleNamespace(content=alert_dialog_content)
accordion = SimpleNamespace(trigger=accordion_trigger, item=accordion_item)
menu = SimpleNamespace(content=menu_content, item=menu_item)
select = SimpleNamespace(
    trigger=select_trigger, content=select_content, item=select_item
)

__all__ = [
    "ExperimentalThemePlugin",
    "accordion",
    "alert_dialog",
    "avatar",
    "badge",
    "blockquote",
    "box",
    "button",
    "callout",
    "card",
    "checkbox",
    "cn",
    "code",
    "container",
    "data_list",
    "dialog",
    "em",
    "flex",
    "grid",
    "heading",
    "hover_card",
    "inset",
    "link",
    "menu",
    "popover",
    "progress",
    "quote",
    "radio",
    "scroll_area",
    "section",
    "segmented_control",
    "select",
    "separator",
    "skeleton",
    "slider",
    "spinner",
    "strong",
    "switch",
    "table",
    "tabs",
    "text",
    "text_area",
    "text_field",
    "tooltip",
]
