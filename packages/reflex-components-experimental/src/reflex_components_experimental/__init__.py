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
from reflex_components_experimental.plugin import ExperimentalThemePlugin
from reflex_components_experimental.utils import cn

# --- simple components ------------------------------------------------------
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
switch = _c.switch
checkbox = _c.checkbox
radio = _c.radio
text_field = _c.text_field
text_area = _c.text_area

# --- compound families ------------------------------------------------------
table = SimpleNamespace(cell=_c.table_cell, header_cell=_c.table_header_cell)
data_list = SimpleNamespace(label=_c.data_list_label, value=_c.data_list_value)
tabs = SimpleNamespace(list=_c.tabs_list, trigger=_c.tabs_trigger)
segmented_control = SimpleNamespace(root=_c.segmented_root, item=_c.segmented_item)
slider = SimpleNamespace(
    track=_c.slider_track, range=_c.slider_range, thumb=_c.slider_thumb
)
progress = SimpleNamespace(root=_c.progress_root, indicator=_c.progress_indicator)
scroll_area = SimpleNamespace(
    scrollbar=_c.scroll_area_scrollbar, thumb=_c.scroll_area_thumb
)
tooltip = SimpleNamespace(content=_c.tooltip_content)
popover = SimpleNamespace(content=_c.popover_content)
hover_card = SimpleNamespace(content=_c.hovercard_content)
dialog = SimpleNamespace(content=_c.dialog_content)
alert_dialog = SimpleNamespace(content=_c.alert_dialog_content)
accordion = SimpleNamespace(trigger=_c.accordion_trigger, item=_c.accordion_item)
menu = SimpleNamespace(content=_c.menu_content, item=_c.menu_item)
select = SimpleNamespace(
    trigger=_c.select_trigger, content=_c.select_content, item=_c.select_item
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
