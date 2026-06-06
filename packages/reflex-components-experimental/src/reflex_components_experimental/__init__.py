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
``rxe.menu.item``, ``rxe.slider.track``, …).
"""

from __future__ import annotations

from types import SimpleNamespace

from reflex_components_experimental import components as _c
from reflex_components_experimental import interactive as _it
from reflex_components_experimental.plugin import ExperimentalThemePlugin
from reflex_components_experimental.utils import cn

# --- static, already-accessible HTML components -----------------------------
button = _c.button
badge = _c.badge
separator = _c.separator
text = _c.text
heading = _c.heading
code = _c.code
em = _c.em
strong = _c.strong
quote = _c.quote
callout = _c.callout
blockquote = _c.blockquote
card = _c.card
avatar = _c.avatar
spinner = _c.spinner
link = _c.link
box = _c.box
flex = _c.flex
grid = _c.grid
container = _c.container
section = _c.section
skeleton = _c.skeleton
inset = _c.inset
text_field = _c.text_field
text_area = _c.text_area
table = SimpleNamespace(cell=_c.table_cell, header_cell=_c.table_header_cell)
data_list = SimpleNamespace(label=_c.data_list_label, value=_c.data_list_value)

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
