"""Radix-parity text area (mirrors ``.rt-TextAreaRoot`` box model).

Root inherits typography (font-size-3/1.5/0) because the per-size font is on the
inner input, not the Root.
"""

import reflex as rx
from reflex_components_experimental.components.text_field import FIELD_VARIANTS
from reflex_components_experimental.utils import merge_class_name

_TA_BASE = (
    "box-border flex flex-col text-start not-italic "
    "font-[family-name:var(--default-font-family)] font-[400] "
    "text-[length:var(--font-size-3)] leading-[1.5] tracking-[0em] "
    "resize-none appearance-none border-0 outline-0 m-0 overflow-hidden [background-clip:content-box]"
)
_TA_SIZES = {
    "1": ("var(--space-8)", "2"),
    "2": ("var(--space-9)", "2"),
    "3": ("80px", "3"),
}


def text_area(
    *children, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful text area (matches .rt-TextAreaRoot box model).

    Args:
        *children: Text content.
        size: "1"-"3".
        variant: classic/surface/soft.
        **props: Extra props.

    Returns:
        The rendered component.
    """
    min_h, radius = _TA_SIZES[size]
    bw, bg, color, shadow = FIELD_VARIANTS[variant]
    cls = f"{_TA_BASE} p-[{bw}] min-h-[{min_h}] rounded-[var(--radius-{radius})] {bg} {color} {shadow}"
    merge_class_name(cls, props)
    props.setdefault("rows", 1)  # let min-height win (match Radix root height)
    return rx.el.textarea(*children, **props)
