"""Low-level Reflex wrappers for Base UI (``@base-ui/react``) headless parts.

Base UI supplies the behavior and accessibility (ARIA roles/states, keyboard
navigation, focus management, type-ahead, focus trapping) that plain HTML
elements lack; the experimental components layer Radix-token Tailwind styling on
top of these parts so the result is both pixel-faithful *and* accessible.

Each part is a thin :class:`~reflex.Component` subclass. The visible npm package
is a versioned root (``@base-ui/react@1.5.0``) declared via ``lib_dependencies``;
parts import from per-component subpaths (e.g. ``@base-ui/react/switch``) with
``install=False`` so the subpath is never mistaken for an installable package.
"""

from __future__ import annotations

from reflex.components.component import Component
from reflex.event import EventHandler, passthrough_event_spec
from reflex.utils.imports import ImportVar
from reflex.vars.base import Var

PKG = "@base-ui/react"
VER = "1.5.0"


class BaseUI(Component):
    """Base for every Base UI part: declares the npm dependency.

    Subclasses set ``library`` to a subpath (``@base-ui/react/<part>``) and a
    dot-qualified ``tag`` (``Switch.Root``); the import is rendered from the
    subpath but not installed (the versioned root below is installed instead).
    """

    lib_dependencies: list[str] = [f"{PKG}@{VER}"]

    @property
    def import_var(self) -> ImportVar:
        """Import the namespace object from the subpath without installing it.

        Returns:
            The import var for this part's namespace (e.g. ``Switch``).
        """
        return ImportVar(tag=(self.tag or "").partition(".")[0], install=False)


def _leaf(subpath: str, tag: str) -> type[BaseUI]:
    """Build a prop-less Base UI part wrapper (children + ``class_name`` only).

    Args:
        subpath: The ``@base-ui/react`` subpath (e.g. ``"dialog"``).
        tag: The dot-qualified component tag (e.g. ``"Dialog.Portal"``).

    Returns:
        A :class:`BaseUI` subclass for that part.
    """
    return type(
        tag.replace(".", ""),
        (BaseUI,),
        {
            "library": f"{PKG}/{subpath}",
            "tag": tag,
            "__module__": __name__,
            "__doc__": f"Base UI {tag} part.",
        },
    )


# Positioner-style props shared by floating popups.
class _Positioner(BaseUI):
    """Shared base for popup positioner parts (side/align/offset props)."""

    side: Var[str]
    align: Var[str]
    side_offset: Var[int]
    align_offset: Var[int]
    sticky: Var[bool]


# --- Switch -----------------------------------------------------------------
class SwitchRoot(BaseUI):
    """Accessible switch root (``role=switch``, space/enter toggle)."""

    library = f"{PKG}/switch"
    tag = "Switch.Root"

    checked: Var[bool]
    default_checked: Var[bool]
    disabled: Var[bool]
    required: Var[bool]
    name: Var[str]
    value: Var[str]
    on_checked_change: EventHandler[passthrough_event_spec(bool)]


SwitchThumb = _leaf("switch", "Switch.Thumb")


# --- Checkbox ---------------------------------------------------------------
class CheckboxRoot(BaseUI):
    """Accessible checkbox root (``role=checkbox``)."""

    library = f"{PKG}/checkbox"
    tag = "Checkbox.Root"

    checked: Var[bool]
    default_checked: Var[bool]
    indeterminate: Var[bool]
    disabled: Var[bool]
    required: Var[bool]
    name: Var[str]
    value: Var[str]
    on_checked_change: EventHandler[passthrough_event_spec(bool)]


CheckboxIndicator = _leaf("checkbox", "Checkbox.Indicator")


# --- Radio ------------------------------------------------------------------
class RadioGroup(BaseUI):
    """Accessible radio group (``role=radiogroup``, arrow-key navigation)."""

    library = f"{PKG}/radio-group"
    tag = "RadioGroup"

    value: Var[str]
    default_value: Var[str]
    disabled: Var[bool]
    required: Var[bool]
    name: Var[str]
    on_value_change: EventHandler[passthrough_event_spec(str)]


class RadioRoot(BaseUI):
    """A single radio item within a radio group."""

    library = f"{PKG}/radio"
    tag = "Radio.Root"

    value: Var[str]
    disabled: Var[bool]


RadioIndicator = _leaf("radio", "Radio.Indicator")


# --- Tabs -------------------------------------------------------------------
class TabsRoot(BaseUI):
    """Tabs root container."""

    library = f"{PKG}/tabs"
    tag = "Tabs.Root"

    value: Var[str]
    default_value: Var[str]
    orientation: Var[str]
    on_value_change: EventHandler[passthrough_event_spec(str)]


TabsList = _leaf("tabs", "Tabs.List")
TabsIndicator = _leaf("tabs", "Tabs.Indicator")


class TabsTab(BaseUI):
    """A single tab trigger (``role=tab``, arrow-key navigable)."""

    library = f"{PKG}/tabs"
    tag = "Tabs.Tab"

    value: Var[str]
    disabled: Var[bool]


class TabsPanel(BaseUI):
    """A tab panel associated with a tab value."""

    library = f"{PKG}/tabs"
    tag = "Tabs.Panel"

    value: Var[str]


# --- Slider -----------------------------------------------------------------
class SliderRoot(BaseUI):
    """Slider root (arrow-key value changes, ``aria-valuenow``)."""

    library = f"{PKG}/slider"
    tag = "Slider.Root"

    value: Var[int | list[int]]
    default_value: Var[int | list[int]]
    min: Var[int]
    max: Var[int]
    step: Var[int]
    disabled: Var[bool]
    orientation: Var[str]
    name: Var[str]
    on_value_change: EventHandler[passthrough_event_spec(int)]
    on_value_committed: EventHandler[passthrough_event_spec(int)]


SliderControl = _leaf("slider", "Slider.Control")
SliderTrack = _leaf("slider", "Slider.Track")
SliderIndicator = _leaf("slider", "Slider.Indicator")
SliderThumb = _leaf("slider", "Slider.Thumb")
SliderValue = _leaf("slider", "Slider.Value")


# --- Progress ---------------------------------------------------------------
class ProgressRoot(BaseUI):
    """Progress root (``role=progressbar`` with value/min/max)."""

    library = f"{PKG}/progress"
    tag = "Progress.Root"

    value: Var[int]
    min: Var[int]
    max: Var[int]


ProgressTrack = _leaf("progress", "Progress.Track")
ProgressIndicator = _leaf("progress", "Progress.Indicator")
ProgressLabel = _leaf("progress", "Progress.Label")


# --- Dialog -----------------------------------------------------------------
class DialogRoot(BaseUI):
    """Dialog root (focus trap, ``aria-modal``, ESC to close)."""

    library = f"{PKG}/dialog"
    tag = "Dialog.Root"

    open: Var[bool]
    default_open: Var[bool]
    modal: Var[bool]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


DialogTrigger = _leaf("dialog", "Dialog.Trigger")
DialogPortal = _leaf("dialog", "Dialog.Portal")
DialogBackdrop = _leaf("dialog", "Dialog.Backdrop")
DialogPopup = _leaf("dialog", "Dialog.Popup")
DialogTitle = _leaf("dialog", "Dialog.Title")
DialogDescription = _leaf("dialog", "Dialog.Description")
DialogClose = _leaf("dialog", "Dialog.Close")


# --- AlertDialog ------------------------------------------------------------
class AlertDialogRoot(BaseUI):
    """Alert dialog root (modal, no dismiss-on-outside-click)."""

    library = f"{PKG}/alert-dialog"
    tag = "AlertDialog.Root"

    open: Var[bool]
    default_open: Var[bool]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


AlertDialogTrigger = _leaf("alert-dialog", "AlertDialog.Trigger")
AlertDialogPortal = _leaf("alert-dialog", "AlertDialog.Portal")
AlertDialogBackdrop = _leaf("alert-dialog", "AlertDialog.Backdrop")
AlertDialogPopup = _leaf("alert-dialog", "AlertDialog.Popup")
AlertDialogTitle = _leaf("alert-dialog", "AlertDialog.Title")
AlertDialogDescription = _leaf("alert-dialog", "AlertDialog.Description")
AlertDialogClose = _leaf("alert-dialog", "AlertDialog.Close")


# --- Popover ----------------------------------------------------------------
class PopoverRoot(BaseUI):
    """Popover root (focus management, ESC/outside-click to close)."""

    library = f"{PKG}/popover"
    tag = "Popover.Root"

    open: Var[bool]
    default_open: Var[bool]
    modal: Var[bool]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


PopoverTrigger = _leaf("popover", "Popover.Trigger")
PopoverPortal = _leaf("popover", "Popover.Portal")
PopoverBackdrop = _leaf("popover", "Popover.Backdrop")
PopoverTitle = _leaf("popover", "Popover.Title")
PopoverDescription = _leaf("popover", "Popover.Description")
PopoverClose = _leaf("popover", "Popover.Close")
PopoverArrow = _leaf("popover", "Popover.Arrow")


class PopoverPositioner(_Positioner):
    """Popover positioner (anchored placement)."""

    library = f"{PKG}/popover"
    tag = "Popover.Positioner"


PopoverPopup = _leaf("popover", "Popover.Popup")


# --- Tooltip ----------------------------------------------------------------
class TooltipProvider(BaseUI):
    """Tooltip provider (shared open/close delays)."""

    library = f"{PKG}/tooltip"
    tag = "Tooltip.Provider"

    delay: Var[int]
    close_delay: Var[int]


class TooltipRoot(BaseUI):
    """Tooltip root (``role=tooltip`` popup, hover/focus triggered)."""

    library = f"{PKG}/tooltip"
    tag = "Tooltip.Root"

    open: Var[bool]
    default_open: Var[bool]
    delay: Var[int]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


TooltipTrigger = _leaf("tooltip", "Tooltip.Trigger")
TooltipPortal = _leaf("tooltip", "Tooltip.Portal")
TooltipArrow = _leaf("tooltip", "Tooltip.Arrow")


class TooltipPositioner(_Positioner):
    """Tooltip positioner (anchored placement)."""

    library = f"{PKG}/tooltip"
    tag = "Tooltip.Positioner"


TooltipPopup = _leaf("tooltip", "Tooltip.Popup")


# --- PreviewCard (hover card) -----------------------------------------------
class PreviewCardRoot(BaseUI):
    """Preview/hover card root (hover-triggered, focusable content)."""

    library = f"{PKG}/preview-card"
    tag = "PreviewCard.Root"

    open: Var[bool]
    default_open: Var[bool]
    delay: Var[int]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


PreviewCardTrigger = _leaf("preview-card", "PreviewCard.Trigger")
PreviewCardPortal = _leaf("preview-card", "PreviewCard.Portal")
PreviewCardArrow = _leaf("preview-card", "PreviewCard.Arrow")


class PreviewCardPositioner(_Positioner):
    """Preview card positioner (anchored placement)."""

    library = f"{PKG}/preview-card"
    tag = "PreviewCard.Positioner"


PreviewCardPopup = _leaf("preview-card", "PreviewCard.Popup")


# --- Menu -------------------------------------------------------------------
class MenuRoot(BaseUI):
    """Dropdown menu root (roving focus, type-ahead, ESC to close)."""

    library = f"{PKG}/menu"
    tag = "Menu.Root"

    open: Var[bool]
    default_open: Var[bool]
    modal: Var[bool]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


MenuTrigger = _leaf("menu", "Menu.Trigger")
MenuPortal = _leaf("menu", "Menu.Portal")
MenuBackdrop = _leaf("menu", "Menu.Backdrop")
MenuPopup = _leaf("menu", "Menu.Popup")
MenuGroup = _leaf("menu", "Menu.Group")
MenuGroupLabel = _leaf("menu", "Menu.GroupLabel")
MenuArrow = _leaf("menu", "Menu.Arrow")


class MenuPositioner(_Positioner):
    """Menu positioner (anchored placement)."""

    library = f"{PKG}/menu"
    tag = "Menu.Positioner"


class MenuItem(BaseUI):
    """A menu item (``role=menuitem``, keyboard-activatable)."""

    library = f"{PKG}/menu"
    tag = "Menu.Item"

    disabled: Var[bool]
    close_on_click: Var[bool]
    on_click: EventHandler[list]


# --- Select -----------------------------------------------------------------
class SelectRoot(BaseUI):
    """Select root (``role=combobox``/``listbox``, type-ahead)."""

    library = f"{PKG}/select"
    tag = "Select.Root"

    value: Var[str]
    default_value: Var[str]
    open: Var[bool]
    default_open: Var[bool]
    name: Var[str]
    disabled: Var[bool]
    required: Var[bool]
    on_value_change: EventHandler[passthrough_event_spec(str)]
    on_open_change: EventHandler[passthrough_event_spec(bool)]


SelectTrigger = _leaf("select", "Select.Trigger")
SelectIcon = _leaf("select", "Select.Icon")
SelectPortal = _leaf("select", "Select.Portal")
SelectBackdrop = _leaf("select", "Select.Backdrop")
SelectPopup = _leaf("select", "Select.Popup")
SelectItemText = _leaf("select", "Select.ItemText")
SelectItemIndicator = _leaf("select", "Select.ItemIndicator")
SelectList = _leaf("select", "Select.List")


class SelectValue(BaseUI):
    """The select trigger's current-value display."""

    library = f"{PKG}/select"
    tag = "Select.Value"

    placeholder: Var[str]


class SelectPositioner(_Positioner):
    """Select positioner (anchored placement)."""

    library = f"{PKG}/select"
    tag = "Select.Positioner"


class SelectItem(BaseUI):
    """A select option (``role=option``)."""

    library = f"{PKG}/select"
    tag = "Select.Item"

    value: Var[str]
    disabled: Var[bool]


# --- Accordion --------------------------------------------------------------
class AccordionRoot(BaseUI):
    """Accordion root (header/trigger/panel ARIA wiring)."""

    library = f"{PKG}/accordion"
    tag = "Accordion.Root"

    value: Var[list[str]]
    default_value: Var[list[str]]
    open_multiple: Var[bool]
    disabled: Var[bool]
    on_value_change: EventHandler[passthrough_event_spec(list)]


AccordionHeader = _leaf("accordion", "Accordion.Header")
AccordionPanel = _leaf("accordion", "Accordion.Panel")


class AccordionItem(BaseUI):
    """An accordion item."""

    library = f"{PKG}/accordion"
    tag = "Accordion.Item"

    value: Var[str]
    disabled: Var[bool]


AccordionTrigger = _leaf("accordion", "Accordion.Trigger")


# --- ToggleGroup (SegmentedControl) -----------------------------------------
class ToggleGroup(BaseUI):
    """Toggle group (single/multiple pressed toggles, arrow-key navigation)."""

    library = f"{PKG}/toggle-group"
    tag = "ToggleGroup"

    value: Var[list[str]]
    default_value: Var[list[str]]
    toggle_multiple: Var[bool]
    disabled: Var[bool]
    on_value_change: EventHandler[passthrough_event_spec(list)]


class Toggle(BaseUI):
    """A single toggle button (``aria-pressed``)."""

    library = f"{PKG}/toggle"
    tag = "Toggle"

    value: Var[str]
    pressed: Var[bool]
    default_pressed: Var[bool]
    disabled: Var[bool]
    on_pressed_change: EventHandler[passthrough_event_spec(bool)]


# --- ScrollArea -------------------------------------------------------------
ScrollAreaRoot = _leaf("scroll-area", "ScrollArea.Root")
ScrollAreaViewport = _leaf("scroll-area", "ScrollArea.Viewport")
ScrollAreaContent = _leaf("scroll-area", "ScrollArea.Content")
ScrollAreaCorner = _leaf("scroll-area", "ScrollArea.Corner")
ScrollAreaThumb = _leaf("scroll-area", "ScrollArea.Thumb")


class ScrollAreaScrollbar(BaseUI):
    """A scroll-area scrollbar (orientation-aware)."""

    library = f"{PKG}/scroll-area"
    tag = "ScrollArea.Scrollbar"

    orientation: Var[str]
