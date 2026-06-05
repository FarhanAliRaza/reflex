"""Spike: a Base UI Switch (headless) styled by an atomic CSS module.

Behavior comes from Base UI (`@base-ui/react/switch`); styling comes from a
co-located ``switch.module.css`` that ``composes`` shared atoms. Nothing about
the Radix Themes design-token/runtime stylesheet is involved.
"""

from pathlib import Path

from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars.base import Var
from reflex_base.components.css_module import CSSModuleComponent

_HERE = Path(__file__).parent
_PKG = "@base-ui/react"
_VER = "1.5.0"


class _SwitchBase(CSSModuleComponent):
    """Shared base wiring Base UI's switch import + the atomic CSS module."""

    library = f"{_PKG}/switch"
    lib_dependencies: list[str] = [f"{_PKG}@{_VER}"]

    _css_module = str(_HERE / "switch.module.css")
    _css_module_shared = (str(_HERE / "_atoms.module.css"),)

    @property
    def import_var(self):
        """Import the `Switch` namespace object from Base UI.

        Returns:
            The import var for the Base UI switch namespace.
        """
        return ImportVar(tag="Switch", package_path="", install=False)


class SwitchRoot(_SwitchBase):
    """The switch track (renders a <button> + hidden input)."""

    tag = "Switch.Root"
    _css_module_class = "root"

    checked: Var[bool]
    default_checked: Var[bool]
    disabled: Var[bool]
    on_checked_change: EventHandler[passthrough_event_spec(bool)]


class SwitchThumb(_SwitchBase):
    """The moving thumb (renders a <span>)."""

    tag = "Switch.Thumb"
    _css_module_class = "thumb"


def switch(**props):
    """Create a Base UI switch with the atomic-module styling.

    Args:
        **props: Props forwarded to the switch root.

    Returns:
        The composed switch component.
    """
    return SwitchRoot.create(SwitchThumb.create(), **props)
