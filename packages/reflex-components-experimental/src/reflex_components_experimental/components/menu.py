"""Radix-parity dropdown/context menu content panel + item (size 2, solid)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_MENU_CONTENT = (
    "flex flex-col box-border overflow-hidden bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)] "
    "rounded-[var(--radius-4)]"
)
_MENU_ITEM = (
    "flex items-center gap-[var(--space-2)] box-border relative outline-none select-none "
    "h-[var(--space-6)] pl-[var(--space-3)] pr-[var(--space-3)] "
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] tracking-[var(--letter-spacing-2)] "
    "rounded-[var(--radius-2)] text-[var(--gray-12)]"
)


def menu_content(*children, **props) -> rx.Component:
    """A Radix-faithful dropdown/context menu content panel (size 2, solid).

    Radix nests a padded viewport inside the (zero-padding) content; mirror that
    so the content box size matches.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_MENU_CONTENT, props.pop("class_name", ""))
    return rx.el.div(
        rx.el.div(*children, class_name="flex flex-col p-[var(--space-2)]"), **props
    )


def menu_item(text: str, highlighted: bool = False, **props) -> rx.Component:
    """A Radix-faithful menu item (size 2).

    Returns:
        The rendered component.
    """
    cls = _MENU_ITEM + (
        " bg-[var(--accent-9)] text-[var(--accent-contrast)]" if highlighted else ""
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(text, **props)
