"""Radix-parity table cells (``.rt-TableCell`` / ``.rt-TableColumnHeaderCell``)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_TABLE_SIZES = {
    "1": ("p-[var(--space-2)]", "36px", "2"),
    "2": ("p-[var(--space-3)]", "44px", "2"),
    "3": ("py-[var(--space-3)] px-[var(--space-4)]", "var(--space-8)", "3"),
}
_TABLE_CELL_BASE = (
    "box-border [vertical-align:inherit] text-left bg-transparent "
    "text-[var(--gray-12)] shadow-[inset_0_-1px_var(--gray-a5)]"
)


def _table_cell_classes(size: str, header: bool) -> str:
    pad, min_h, fs = _TABLE_SIZES[size]
    weight = "font-bold" if header else "font-normal"
    return (
        f"{_TABLE_CELL_BASE} {pad} h-[{min_h}] {weight} "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] "
        f"font-[family-name:var(--default-font-family)]"
    )


def table_cell(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful table body cell (<td>).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        _table_cell_classes(size, False), props.pop("class_name", "")
    )
    return rx.el.td(*children, **props)


def table_header_cell(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful table column header cell (<th>, bold).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        _table_cell_classes(size, True), props.pop("class_name", "")
    )
    return rx.el.th(*children, **props)
