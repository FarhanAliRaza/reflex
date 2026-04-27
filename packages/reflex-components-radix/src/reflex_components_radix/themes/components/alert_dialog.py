"""AlertDialog — wraps ``@radix-ui/react-alert-dialog`` with Tailwind styling.

The original Radix Themes AlertDialog auto-wrapped content in
Portal + Overlay. This rewrite uses the bare primitive directly and
attaches Tailwind class strings for the overlay + content panel.
``@radix-ui/themes`` is no longer required.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import (
    dialog_content_classes,
    dialog_overlay_classes,
)
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.base import (
    RadixPrimitiveComponent,
    RadixPrimitiveTriggerComponent,
)
from reflex_components_radix.themes.base import apply_portal_theme


class _AlertDialogElement(RadixPrimitiveComponent):
    """Base for @radix-ui/react-alert-dialog components."""

    library = "@radix-ui/react-alert-dialog@1.1.15"


class AlertDialogRoot(_AlertDialogElement):
    """Root component for AlertDialog."""

    tag = "Root"
    alias = "RadixPrimitiveAlertDialogRoot"

    open: Var[bool] = field(doc="Controlled open state")
    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")
    default_open: Var[bool] = field(doc="Initial open state")

    _valid_children: ClassVar[list[str]] = [
        "AlertDialogTrigger",
        "AlertDialogPortal",
    ]


class AlertDialogPortal(_AlertDialogElement):
    """Portal for AlertDialog content."""

    tag = "Portal"
    alias = "RadixPrimitiveAlertDialogPortal"

    force_mount: Var[bool] = field(doc="Force mount")

    _valid_parents: ClassVar[list[str]] = ["AlertDialogRoot"]


class AlertDialogOverlay(_AlertDialogElement):
    """Backdrop covering inert content."""

    tag = "Overlay"
    alias = "RadixPrimitiveAlertDialogOverlay"

    force_mount: Var[bool] = field(doc="Force mount")

    _valid_parents: ClassVar[list[str]] = ["AlertDialogPortal"]


class AlertDialogTrigger(_AlertDialogElement, RadixPrimitiveTriggerComponent):
    """Trigger that opens the dialog."""

    tag = "Trigger"
    alias = "RadixPrimitiveAlertDialogTrigger"

    _memoization_mode = MemoizationMode(recursive=False)
    _valid_parents: ClassVar[list[str]] = ["AlertDialogRoot"]


class AlertDialogContent(elements.Div, _AlertDialogElement):
    """Dialog content panel — auto-wraps in Portal + Overlay."""

    tag = "Content"
    alias = "RadixPrimitiveAlertDialogContent"

    size: Var[Responsive[Literal["1", "2", "3", "4"]]] = field(doc='Size "1"-"4"')
    force_mount: Var[bool] = field(doc="Force mount")

    on_open_auto_focus: EventHandler[no_args_event_spec] = field(doc="Open focus.")
    on_close_auto_focus: EventHandler[no_args_event_spec] = field(doc="Close focus.")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")

    _valid_parents: ClassVar[list[str]] = ["AlertDialogPortal"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create alert-dialog content wrapped in Portal + Overlay.

        Args:
            *children: Dialog body.
            **props: Standard content props.

        Returns:
            The content component (already inside a portal/overlay).
        """
        existing = props.pop("class_name", "")
        props.pop("size", None)
        props["class_name"] = cn(dialog_content_classes(), existing)
        apply_portal_theme(props)
        content = super().create(*children, **props)
        return AlertDialogPortal.create(
            AlertDialogOverlay.create(class_name=dialog_overlay_classes()),
            content,
        )


class AlertDialogTitle(_AlertDialogElement):
    """Dialog title (accessible)."""

    tag = "Title"
    alias = "RadixPrimitiveAlertDialogTitle"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create the dialog title.

        Args:
            *children: Title content.
            **props: Standard props.

        Returns:
            The title component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "text-lg font-semibold text-[var(--gray-12)] mb-1", existing,
        )
        return super().create(*children, **props)


class AlertDialogDescription(_AlertDialogElement):
    """Dialog description (accessible)."""

    tag = "Description"
    alias = "RadixPrimitiveAlertDialogDescription"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create the dialog description.

        Args:
            *children: Description content.
            **props: Standard props.

        Returns:
            The description component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "text-sm text-[var(--gray-11)] mb-3", existing,
        )
        return super().create(*children, **props)


class AlertDialogAction(_AlertDialogElement, RadixPrimitiveTriggerComponent):
    """The destructive / confirming action that closes the dialog."""

    tag = "Action"
    alias = "RadixPrimitiveAlertDialogAction"


class AlertDialogCancel(_AlertDialogElement, RadixPrimitiveTriggerComponent):
    """The cancel action that closes the dialog."""

    tag = "Cancel"
    alias = "RadixPrimitiveAlertDialogCancel"


class AlertDialog(ComponentNamespace):
    """AlertDialog components namespace."""

    root = staticmethod(AlertDialogRoot.create)
    trigger = staticmethod(AlertDialogTrigger.create)
    content = staticmethod(AlertDialogContent.create)
    title = staticmethod(AlertDialogTitle.create)
    description = staticmethod(AlertDialogDescription.create)
    action = staticmethod(AlertDialogAction.create)
    cancel = staticmethod(AlertDialogCancel.create)


alert_dialog = AlertDialog()
