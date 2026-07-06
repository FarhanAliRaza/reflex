"""Custom radio component."""

from reflex.components.component import Component, ComponentNamespace
from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars.base import Var
from reflex_components_internal.components.base_ui import PACKAGE_NAME, BaseUIComponent


class RadioGroupBaseComponent(BaseUIComponent):
    """Base component for the radio group part."""

    library = f"{PACKAGE_NAME}/radio-group"

    @property
    def import_var(self):
        """Return the import variable for the radio group component."""
        return ImportVar(tag="RadioGroup", package_path="", install=False)


class RadioBaseComponent(BaseUIComponent):
    """Base component for radio parts."""

    library = f"{PACKAGE_NAME}/radio"

    @property
    def import_var(self):
        """Return the import variable for the radio component."""
        return ImportVar(tag="Radio", package_path="", install=False)


class RadioGroup(RadioGroupBaseComponent):
    """Groups radio items and manages their shared state (role=radiogroup). Renders a <div> element."""

    tag = "RadioGroup"

    # The controlled value of the selected radio item. To render an uncontrolled group, use the default_value prop instead.
    value: Var[str]

    # The uncontrolled value of the initially selected radio item.
    default_value: Var[str]

    # Event handler called when the selected radio item changes.
    on_value_change: EventHandler[passthrough_event_spec(str)]

    # Identifies the field when a form is submitted.
    name: Var[str]

    # Whether the component should ignore user interaction. Defaults to False.
    disabled: Var[bool]

    # Whether the user should be unable to select a different radio item. Defaults to False.
    read_only: Var[bool]

    # Whether the user must select a radio item before submitting a form. Defaults to False.
    required: Var[bool]

    # The render prop
    render_: Var[Component]


class RadioRoot(RadioBaseComponent):
    """Represents the radio button itself (role=radio). Renders a <span> element and a hidden <input> beside it."""

    tag = "Radio.Root"

    # The unique identifying value of the radio in a group.
    value: Var[str]

    # Whether the component renders a native <button> element when replacing it via the render prop. Set to false if the rendered element is not a button (e.g. <div>). Defaults to True.
    native_button: Var[bool]

    # Whether the component should ignore user interaction. Defaults to False.
    disabled: Var[bool]

    # Whether the user should be unable to select the radio button. Defaults to False.
    read_only: Var[bool]

    # Whether the user must select the radio button before submitting a form. Defaults to False.
    required: Var[bool]

    # The render prop
    render_: Var[Component]


class RadioIndicator(RadioBaseComponent):
    """Indicates whether the radio button is selected. Renders a <span> element."""

    tag = "Radio.Indicator"

    # Whether to keep the element in the DOM while the radio button is inactive. Defaults to False.
    keep_mounted: Var[bool]

    # The render prop
    render_: Var[Component]


class Radio(ComponentNamespace):
    """Namespace for Radio components."""

    group = staticmethod(RadioGroup.create)
    root = staticmethod(RadioRoot.create)
    indicator = staticmethod(RadioIndicator.create)
    __call__ = staticmethod(RadioRoot.create)


radio = Radio()
