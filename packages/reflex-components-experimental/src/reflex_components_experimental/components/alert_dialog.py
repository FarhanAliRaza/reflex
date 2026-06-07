"""Radix-parity AlertDialog content panel (size 3, same box as Dialog)."""

import reflex as rx
from reflex_components_experimental.components.dialog import _DIALOG_CONTENT
from reflex_components_experimental.utils import cn


def alert_dialog_content(*children, **props) -> rx.Component:
    """A Radix-faithful AlertDialog content panel (size 3).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)
