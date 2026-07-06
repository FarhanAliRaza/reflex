"""Custom progress component."""

from reflex.components.component import Component, ComponentNamespace
from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars.base import Var
from reflex_components_internal.components.base_ui import PACKAGE_NAME, BaseUIComponent


class ProgressBaseComponent(BaseUIComponent):
    """Base component for progress parts."""

    library = f"{PACKAGE_NAME}/progress"

    @property
    def import_var(self):
        """Return the import variable for the progress component."""
        return ImportVar(tag="Progress", package_path="", install=False)


class ProgressRoot(ProgressBaseComponent):
    """Groups all parts of the progress bar and provides the task completion status to screen readers (role=progressbar). Renders a <div> element."""

    tag = "Progress.Root"

    # The current value. The component is indeterminate when value is None. Defaults to None.
    value: Var[int]

    # The minimum value. Defaults to 0.
    min: Var[int]

    # The maximum value. Defaults to 100.
    max: Var[int]

    # A string value that provides a human-readable text alternative to the current value of the progress bar.
    locale: Var[str]

    # Event handler called when the progress value changes.
    on_value_change: EventHandler[passthrough_event_spec(int)]

    # The render prop
    render_: Var[Component]


class ProgressTrack(ProgressBaseComponent):
    """Contains the progress bar indicator. Renders a <div> element."""

    tag = "Progress.Track"

    # The render prop
    render_: Var[Component]


class ProgressIndicator(ProgressBaseComponent):
    """Visualizes the completion status of the task. Renders a <div> element."""

    tag = "Progress.Indicator"

    # The render prop
    render_: Var[Component]


class ProgressLabel(ProgressBaseComponent):
    """An accessible label for the progress bar. Renders a <span> element."""

    tag = "Progress.Label"

    # The render prop
    render_: Var[Component]


class ProgressValue(ProgressBaseComponent):
    """A text element displaying the current value. Renders a <span> element."""

    tag = "Progress.Value"

    # The render prop
    render_: Var[Component]


class Progress(ComponentNamespace):
    """Namespace for Progress components."""

    root = staticmethod(ProgressRoot.create)
    track = staticmethod(ProgressTrack.create)
    indicator = staticmethod(ProgressIndicator.create)
    label = staticmethod(ProgressLabel.create)
    value = staticmethod(ProgressValue.create)
    __call__ = staticmethod(ProgressRoot.create)


progress = Progress()
