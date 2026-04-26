"""Dialog — re-exports the @radix-ui/react-dialog primitive with Tailwind styling.

The original Radix Themes Dialog auto-wrapped content in
Dialog.Portal + Dialog.Overlay; this rewrite preserves that flow but
uses the bare ``@radix-ui/react-dialog`` primitive (already vendored
in ``reflex_components_radix.primitives.dialog``), with a small
class-name layer for the overlay + content surfaces. No
``@radix-ui/themes`` dependency.
"""

from __future__ import annotations

from typing import Any, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.event import EventHandler, no_args_event_spec, passthrough_event_spec
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive

from reflex_components_radix._radix_classes import (
    dialog_content_classes,
    dialog_overlay_classes,
)
from reflex_components_radix._variants import cn
from reflex_components_radix.primitives.dialog import (
    DialogClose as _PrimitiveDialogClose,
    DialogContent as _PrimitiveDialogContent,
    DialogDescription as _PrimitiveDialogDescription,
    DialogOverlay as _PrimitiveDialogOverlay,
    DialogPortal as _PrimitiveDialogPortal,
    DialogRoot as _PrimitiveDialogRoot,
    DialogTitle as _PrimitiveDialogTitle,
    DialogTrigger as _PrimitiveDialogTrigger,
)


class DialogRoot(_PrimitiveDialogRoot):
    """Root component for Dialog."""

    open: Var[bool] = field(doc="Controlled open state")
    on_open_change: EventHandler[passthrough_event_spec(bool)] = field(doc="Open change.")
    default_open: Var[bool] = field(doc="Initial open state")


class DialogTrigger(_PrimitiveDialogTrigger):
    """Button that opens the dialog."""

    _memoization_mode = MemoizationMode(recursive=False)


class DialogTitle(_PrimitiveDialogTitle):
    """Dialog title."""

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a dialog title.

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


class DialogContent(_PrimitiveDialogContent):
    """Dialog content panel — auto-wraps in Portal + Overlay."""

    size: Var[Responsive[Literal["1", "2", "3", "4"]]] = field(doc='Size "1"-"4"')

    on_open_auto_focus: EventHandler[no_args_event_spec] = field(doc="Open focus.")
    on_close_auto_focus: EventHandler[no_args_event_spec] = field(doc="Close focus.")
    on_escape_key_down: EventHandler[no_args_event_spec] = field(doc="Escape down.")
    on_pointer_down_outside: EventHandler[no_args_event_spec] = field(doc="Pointer down outside.")
    on_interact_outside: EventHandler[no_args_event_spec] = field(doc="Interact outside.")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create dialog content wrapped in Portal + Overlay.

        Args:
            *children: Dialog body.
            **props: standard content props.

        Returns:
            The content component (already inside a portal/overlay).
        """
        existing = props.pop("class_name", "")
        props.pop("size", None)
        props["class_name"] = cn(dialog_content_classes(), existing)
        content = super().create(*children, **props)
        return _PrimitiveDialogPortal.create(
            _PrimitiveDialogOverlay.create(class_name=dialog_overlay_classes()),
            content,
        )


class DialogDescription(_PrimitiveDialogDescription):
    """Dialog description."""

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a dialog description.

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


class DialogClose(_PrimitiveDialogClose):
    """Close button."""


class Dialog(ComponentNamespace):
    """Dialog components namespace."""

    root = __call__ = staticmethod(DialogRoot.create)
    trigger = staticmethod(DialogTrigger.create)
    title = staticmethod(DialogTitle.create)
    content = staticmethod(DialogContent.create)
    description = staticmethod(DialogDescription.create)
    close = staticmethod(DialogClose.create)


dialog = Dialog()
