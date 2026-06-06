"""Self-contained Base UI + atomic-Tailwind components for the spike.

Demonstrates the RFC's proposed stack end to end:
- behavior/accessibility from `@base-ui/react` (headless),
- styling from Tailwind utility classes against the swappable token theme
  (`assets/theme.css`),
- deterministic user overrides via `cn()` (clsx-for-tailwind / tailwind-merge).
"""

from reflex.components.component import Component, ComponentNamespace
from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars import FunctionVar
from reflex.vars.base import Var, VarData

_PKG = "@base-ui/react"
_VER = "1.5.0"

# clsx + tailwind-merge: later (user) utilities win over conflicting defaults.
_CN = Var(
    "cn",
    _var_data=VarData(imports={"clsx-for-tailwind@1.0.0": ImportVar(tag="cn")}),
).to(FunctionVar)


def cn(*classes) -> Var:
    """Merge tailwind class strings/Vars with conflict resolution.

    Args:
        *classes: Class strings or Vars.

    Returns:
        A Var of the merged class string.
    """
    return _CN.call(*classes).to(str)


def _merge(default: str, props: dict) -> None:
    """Merge a component's default classes with any user ``class_name``."""
    props["class_name"] = cn(default, props.pop("class_name", ""))


class _BaseUI(Component):
    """Base for Base UI components (declares the npm dependency)."""

    lib_dependencies: list[str] = [f"{_PKG}@{_VER}"]


# --- Button (plain element, atomic-styled, overridable) ---------------------

BTN = (
    "inline-flex items-center justify-center gap-2 h-9 px-4 rounded-[var(--radius)] "
    "text-sm font-medium text-[var(--white)] bg-[var(--primary-9)] "
    "hover:bg-[var(--primary-10)] active:bg-[var(--primary-10)] "
    "focus-visible:outline-2 focus-visible:outline-offset-2 "
    "focus-visible:outline-[var(--primary-8)] transition-colors cursor-pointer "
    "select-none disabled:opacity-50"
)


def button(*children, **props) -> Component:
    """A solid, atomic-styled button; ``class_name`` overrides win via cn.

    Args:
        *children: Button content.
        **props: Element props (incl. ``class_name`` to override).

    Returns:
        The button component.
    """
    import reflex as rx

    _merge(BTN, props)
    return rx.el.button(*children, **props)


# --- Switch (Base UI) -------------------------------------------------------

_SWITCH_ROOT = (
    "relative inline-flex items-center h-[22px] w-[38px] shrink-0 rounded-full "
    "bg-[var(--secondary-7)] p-[2px] transition-colors cursor-pointer "
    "data-[checked]:bg-[var(--primary-9)] focus-visible:outline-2 "
    "focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-8)]"
)
_SWITCH_THUMB = (
    "block h-[18px] w-[18px] rounded-full bg-[var(--white)] "
    "shadow-[0_1px_2px_rgba(0,0,0,0.25)] transition-transform "
    "data-[checked]:translate-x-4"
)


class _SwitchBase(_BaseUI):
    library = f"{_PKG}/switch"

    @property
    def import_var(self):  # noqa: D102
        return ImportVar(tag="Switch", package_path="", install=False)


class SwitchRoot(_SwitchBase):
    """The switch track."""

    tag = "Switch.Root"
    checked: Var[bool]
    default_checked: Var[bool]
    disabled: Var[bool]
    on_checked_change: EventHandler[passthrough_event_spec(bool)]

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_SWITCH_ROOT, props)
        return super().create(*children, **props)


class SwitchThumb(_SwitchBase):
    """The moving thumb."""

    tag = "Switch.Thumb"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_SWITCH_THUMB, props)
        return super().create(*children, **props)


def switch(**props) -> Component:
    """A Base UI switch with atomic styling.

    Args:
        **props: Props for the switch root.

    Returns:
        The switch component.
    """
    return SwitchRoot.create(SwitchThumb.create(), **props)


# --- Dialog (Base UI) -------------------------------------------------------

_BACKDROP = (
    "fixed inset-0 bg-black/40 transition-opacity duration-150 "
    "data-[ending-style]:opacity-0 data-[starting-style]:opacity-0"
)
_POPUP = (
    "fixed top-1/2 left-1/2 w-[28rem] max-w-[calc(100vw-2rem)] -translate-x-1/2 "
    "-translate-y-1/2 rounded-[var(--radius)] border border-[var(--secondary-6)] "
    "bg-[var(--secondary-1)] p-6 shadow-[0_10px_38px_rgba(0,0,0,0.35)] "
    "transition-all duration-150 data-[ending-style]:scale-95 "
    "data-[ending-style]:opacity-0 data-[starting-style]:scale-95 "
    "data-[starting-style]:opacity-0"
)
_TITLE = "text-xl font-semibold text-[var(--secondary-12)]"
_DESC = "mt-1 text-sm text-[var(--secondary-11)]"


class _DialogBase(_BaseUI):
    library = f"{_PKG}/dialog"

    @property
    def import_var(self):  # noqa: D102
        return ImportVar(tag="Dialog", package_path="", install=False)


class DialogRoot(_DialogBase):
    """Dialog root."""

    tag = "Dialog.Root"
    open: Var[bool]
    default_open: Var[bool]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


class DialogTrigger(_DialogBase):
    tag = "Dialog.Trigger"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(BTN, props)
        return super().create(*children, **props)


class DialogPortal(_DialogBase):
    tag = "Dialog.Portal"


class DialogBackdrop(_DialogBase):
    tag = "Dialog.Backdrop"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_BACKDROP, props)
        return super().create(*children, **props)


class DialogPopup(_DialogBase):
    tag = "Dialog.Popup"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_POPUP, props)
        return super().create(*children, **props)


class DialogTitle(_DialogBase):
    tag = "Dialog.Title"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_TITLE, props)
        return super().create(*children, **props)


class DialogDescription(_DialogBase):
    tag = "Dialog.Description"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(_DESC, props)
        return super().create(*children, **props)


class DialogClose(_DialogBase):
    tag = "Dialog.Close"

    @classmethod
    def create(cls, *children, **props):  # noqa: D102
        _merge(BTN, props)
        return super().create(*children, **props)


class Dialog(ComponentNamespace):
    """Base UI dialog namespace."""

    root = staticmethod(DialogRoot.create)
    trigger = staticmethod(DialogTrigger.create)
    portal = staticmethod(DialogPortal.create)
    backdrop = staticmethod(DialogBackdrop.create)
    popup = staticmethod(DialogPopup.create)
    title = staticmethod(DialogTitle.create)
    description = staticmethod(DialogDescription.create)
    close = staticmethod(DialogClose.create)


dialog = Dialog()
