"""Custom alert dialog component."""

from reflex.components.component import Component, ComponentNamespace
from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars.base import Var
from reflex_components_internal.components.base_ui import PACKAGE_NAME, BaseUIComponent


class AlertDialogBaseComponent(BaseUIComponent):
    """Base component for alert dialog parts."""

    library = f"{PACKAGE_NAME}/alert-dialog"

    @property
    def import_var(self):
        """Return the import variable for the alert dialog component."""
        return ImportVar(tag="AlertDialog", package_path="", install=False)


class AlertDialogRoot(AlertDialogBaseComponent):
    """Groups all parts of the alert dialog. Doesn't render its own HTML element."""

    tag = "AlertDialog.Root"

    # Whether the dialog is currently open. To render an uncontrolled dialog, use the default_open prop instead.
    open: Var[bool]

    # Whether the dialog is initially open. To render a controlled dialog, use the open prop instead. Defaults to False.
    default_open: Var[bool]

    # Event handler called when the dialog is opened or closed.
    on_open_change: EventHandler[passthrough_event_spec(bool)]

    # Event handler called after any animations complete when the dialog is opened or closed.
    on_open_change_complete: EventHandler[passthrough_event_spec(bool)]


class AlertDialogTrigger(AlertDialogBaseComponent):
    """A button that opens the alert dialog. Renders a <button> element."""

    tag = "AlertDialog.Trigger"

    # Whether the component renders a native <button> element when replacing it via the render prop. Set to false if the rendered element is not a button (e.g. <div>). Defaults to True.
    native_button: Var[bool]

    # Whether the component should ignore user interaction. Defaults to False.
    disabled: Var[bool]

    # The render prop
    render_: Var[Component]


class AlertDialogPortal(AlertDialogBaseComponent):
    """A portal element that moves the popup to a different part of the DOM. By default, the portal element is appended to <body>."""

    tag = "AlertDialog.Portal"

    # Whether to keep the portal mounted in the DOM while the popup is hidden. Defaults to False.
    keep_mounted: Var[bool]


class AlertDialogBackdrop(AlertDialogBaseComponent):
    """An overlay displayed beneath the popup. Renders a <div> element."""

    tag = "AlertDialog.Backdrop"

    # The render prop
    render_: Var[Component]


class AlertDialogPopup(AlertDialogBaseComponent):
    """A container for the alert dialog contents (role=alertdialog). Renders a <div> element."""

    tag = "AlertDialog.Popup"

    # Determines the element to focus when the dialog is opened.
    initial_focus: Var[str]

    # Determines the element to focus when the dialog is closed.
    final_focus: Var[str]

    # The render prop
    render_: Var[Component]


class AlertDialogTitle(AlertDialogBaseComponent):
    """A heading that labels the dialog. Renders an <h2> element."""

    tag = "AlertDialog.Title"

    # The render prop
    render_: Var[Component]


class AlertDialogDescription(AlertDialogBaseComponent):
    """A paragraph with additional information about the alert dialog. Renders a <p> element."""

    tag = "AlertDialog.Description"

    # The render prop
    render_: Var[Component]


class AlertDialogClose(AlertDialogBaseComponent):
    """A button that closes the alert dialog. Renders a <button> element."""

    tag = "AlertDialog.Close"

    # Whether the component renders a native <button> element when replacing it via the render prop. Set to false if the rendered element is not a button (e.g. <div>). Defaults to True.
    native_button: Var[bool]

    # Whether the component should ignore user interaction. Defaults to False.
    disabled: Var[bool]

    # The render prop
    render_: Var[Component]


class AlertDialog(ComponentNamespace):
    """Namespace for AlertDialog components."""

    root = staticmethod(AlertDialogRoot.create)
    trigger = staticmethod(AlertDialogTrigger.create)
    portal = staticmethod(AlertDialogPortal.create)
    backdrop = staticmethod(AlertDialogBackdrop.create)
    popup = staticmethod(AlertDialogPopup.create)
    title = staticmethod(AlertDialogTitle.create)
    description = staticmethod(AlertDialogDescription.create)
    close = staticmethod(AlertDialogClose.create)


alert_dialog = AlertDialog()
