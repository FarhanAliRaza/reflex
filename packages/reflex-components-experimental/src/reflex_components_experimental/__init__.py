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

Static, already-accessible HTML components (``button``, ``card``, typography,
layout) live in the ``components``, ``layout`` and ``typography`` subpackages.
Interactive widgets that need ARIA/keyboard behavior (``switch``, ``dialog``,
``select`` …) layer the same token styling on Base UI headless parts in the
``interactive`` subpackage. Simple controls are top-level callables; compound
widgets are grouped namespaces (``rxe.tabs.tab``, ``rxe.menu.item``,
``rxe.dialog.popup`` …).
"""

from __future__ import annotations

from types import SimpleNamespace

from reflex_components_experimental import interactive as _it
from reflex_components_experimental.components import (
    avatar,
    badge,
    button,
    callout,
    card,
    data_list_label,
    data_list_value,
    inset,
    separator,
    skeleton,
    spinner,
    table_cell,
    table_header_cell,
    text_area,
    text_field,
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

# --- static compound families -----------------------------------------------
table = SimpleNamespace(cell=table_cell, header_cell=table_header_cell)
data_list = SimpleNamespace(label=data_list_label, value=data_list_value)

# --- accessible interactive components (Base UI behavior) -------------------
# Form controls keep a flat callable API; compound widgets are part namespaces.
switch = _it.switch
checkbox = _it.checkbox
radio = _it.radio
radio_group = _it.radio_group
slider = _it.slider
progress = _it.progress
scroll_area = _it.scroll_area
tabs = _it.tabs
segmented_control = _it.segmented_control
dialog = _it.dialog
alert_dialog = _it.alert_dialog
popover = _it.popover
hover_card = _it.hover_card
tooltip = _it.tooltip
menu = _it.menu
select = _it.select
accordion = _it.accordion

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
    "radio_group",
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
