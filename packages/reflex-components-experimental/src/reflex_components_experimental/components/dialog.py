"""Radix-parity Dialog content panel (size 3)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_DIALOG_CONTENT = (
    "box-border relative overflow-auto outline-none m-auto font-[family-name:var(--default-font-family)] "
    "p-[var(--space-5)] rounded-[var(--radius-5)] bg-[var(--color-panel-solid)] shadow-[var(--shadow-6)] "
    "w-[600px] max-w-[600px]"
)


def dialog_content(*children, **props) -> rx.Component:
    """A Radix-faithful Dialog content panel (size 3).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)
