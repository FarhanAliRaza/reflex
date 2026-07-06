"""Unstyled adapters over ``reflex-components-internal``'s Base UI parts.

The internal package owns the ``@base-ui/react`` wrapper layer (part classes,
props, version pin). Its parts carry the site's default styling in ``create``,
so each adapter here injects ``unstyled=True`` — the experimental components
then layer their own Radix-parity Tailwind classes on the bare parts.
"""

from __future__ import annotations

from collections.abc import Callable

from reflex_components_internal.components.base.accordion import (
    AccordionHeader,
    AccordionItem,
    AccordionPanel,
    AccordionRoot,
    AccordionTrigger,
)
from reflex_components_internal.components.base.alert_dialog import (
    AlertDialogBackdrop,
    AlertDialogClose,
    AlertDialogDescription,
    AlertDialogPopup,
    AlertDialogPortal,
    AlertDialogRoot,
    AlertDialogTitle,
    AlertDialogTrigger,
)
from reflex_components_internal.components.base.checkbox import (
    CheckboxIndicator,
    CheckboxRoot,
)
from reflex_components_internal.components.base.dialog import (
    DialogBackdrop,
    DialogClose,
    DialogDescription,
    DialogPopup,
    DialogPortal,
    DialogRoot,
    DialogTitle,
    DialogTrigger,
)
from reflex_components_internal.components.base.menu import (
    MenuGroup,
    MenuGroupLabel,
    MenuItem,
    MenuPopup,
    MenuPortal,
    MenuPositioner,
    MenuRoot,
    MenuTrigger,
)
from reflex_components_internal.components.base.popover import (
    PopoverClose,
    PopoverDescription,
    PopoverPopup,
    PopoverPortal,
    PopoverPositioner,
    PopoverRoot,
    PopoverTitle,
    PopoverTrigger,
)
from reflex_components_internal.components.base.preview_card import (
    PreviewCardPopup,
    PreviewCardPortal,
    PreviewCardPositioner,
    PreviewCardRoot,
    PreviewCardTrigger,
)
from reflex_components_internal.components.base.progress import (
    ProgressIndicator,
    ProgressRoot,
    ProgressTrack,
)
from reflex_components_internal.components.base.radio import (
    RadioGroup,
    RadioIndicator,
    RadioRoot,
)
from reflex_components_internal.components.base.scroll_area import (
    ScrollAreaRoot,
    ScrollAreaScrollbar,
    ScrollAreaThumb,
    ScrollAreaViewport,
)
from reflex_components_internal.components.base.select import (
    SelectIcon,
    SelectItem,
    SelectItemText,
    SelectPopup,
    SelectPortal,
    SelectPositioner,
    SelectRoot,
    SelectTrigger,
    SelectValue,
)
from reflex_components_internal.components.base.slider import (
    SliderControl,
    SliderIndicator,
    SliderRoot,
    SliderThumb,
    SliderTrack,
)
from reflex_components_internal.components.base.switch import SwitchRoot, SwitchThumb
from reflex_components_internal.components.base.tabs import (
    TabsList,
    TabsPanel,
    TabsRoot,
    TabsTab,
)
from reflex_components_internal.components.base.toggle import Toggle
from reflex_components_internal.components.base.toggle_group import ToggleGroupRoot
from reflex_components_internal.components.base.tooltip import (
    TooltipPopup,
    TooltipPortal,
    TooltipPositioner,
    TooltipProvider,
    TooltipRoot,
    TooltipTrigger,
)

from reflex.components.component import Component


def _unstyled(part: type[Component]) -> Callable[..., Component]:
    """Wrap a part's ``create`` so the internal default styling is skipped.

    Args:
        part: An internal Base UI part component class.

    Returns:
        A create callable that passes ``unstyled=True`` by default.
    """

    def create(*children, **props) -> Component:
        props.setdefault("unstyled", True)
        return part.create(*children, **props)

    return create


switch_root = _unstyled(SwitchRoot)
switch_thumb = _unstyled(SwitchThumb)

checkbox_root = _unstyled(CheckboxRoot)
checkbox_indicator = _unstyled(CheckboxIndicator)

radio_group = _unstyled(RadioGroup)
radio_root = _unstyled(RadioRoot)
radio_indicator = _unstyled(RadioIndicator)

tabs_root = _unstyled(TabsRoot)
tabs_list = _unstyled(TabsList)
tabs_tab = _unstyled(TabsTab)
tabs_panel = _unstyled(TabsPanel)

toggle = _unstyled(Toggle)
toggle_group = _unstyled(ToggleGroupRoot)

slider_root = _unstyled(SliderRoot)
slider_control = _unstyled(SliderControl)
slider_track = _unstyled(SliderTrack)
slider_indicator = _unstyled(SliderIndicator)
slider_thumb = _unstyled(SliderThumb)

progress_root = _unstyled(ProgressRoot)
progress_track = _unstyled(ProgressTrack)
progress_indicator = _unstyled(ProgressIndicator)

scroll_area_root = _unstyled(ScrollAreaRoot)
scroll_area_viewport = _unstyled(ScrollAreaViewport)
scroll_area_scrollbar = _unstyled(ScrollAreaScrollbar)
scroll_area_thumb = _unstyled(ScrollAreaThumb)

dialog_root = _unstyled(DialogRoot)
dialog_trigger = _unstyled(DialogTrigger)
dialog_portal = _unstyled(DialogPortal)
dialog_backdrop = _unstyled(DialogBackdrop)
dialog_popup = _unstyled(DialogPopup)
dialog_title = _unstyled(DialogTitle)
dialog_description = _unstyled(DialogDescription)
dialog_close = _unstyled(DialogClose)

alert_dialog_root = _unstyled(AlertDialogRoot)
alert_dialog_trigger = _unstyled(AlertDialogTrigger)
alert_dialog_portal = _unstyled(AlertDialogPortal)
alert_dialog_backdrop = _unstyled(AlertDialogBackdrop)
alert_dialog_popup = _unstyled(AlertDialogPopup)
alert_dialog_title = _unstyled(AlertDialogTitle)
alert_dialog_description = _unstyled(AlertDialogDescription)
alert_dialog_close = _unstyled(AlertDialogClose)

popover_root = _unstyled(PopoverRoot)
popover_trigger = _unstyled(PopoverTrigger)
popover_portal = _unstyled(PopoverPortal)
popover_positioner = _unstyled(PopoverPositioner)
popover_popup = _unstyled(PopoverPopup)
popover_title = _unstyled(PopoverTitle)
popover_description = _unstyled(PopoverDescription)
popover_close = _unstyled(PopoverClose)

preview_card_root = _unstyled(PreviewCardRoot)
preview_card_trigger = _unstyled(PreviewCardTrigger)
preview_card_portal = _unstyled(PreviewCardPortal)
preview_card_positioner = _unstyled(PreviewCardPositioner)
preview_card_popup = _unstyled(PreviewCardPopup)

tooltip_provider = _unstyled(TooltipProvider)
tooltip_root = _unstyled(TooltipRoot)
tooltip_trigger = _unstyled(TooltipTrigger)
tooltip_portal = _unstyled(TooltipPortal)
tooltip_positioner = _unstyled(TooltipPositioner)
tooltip_popup = _unstyled(TooltipPopup)

menu_root = _unstyled(MenuRoot)
menu_trigger = _unstyled(MenuTrigger)
menu_portal = _unstyled(MenuPortal)
menu_positioner = _unstyled(MenuPositioner)
menu_popup = _unstyled(MenuPopup)
menu_item = _unstyled(MenuItem)
menu_group = _unstyled(MenuGroup)
menu_group_label = _unstyled(MenuGroupLabel)

select_root = _unstyled(SelectRoot)
select_trigger = _unstyled(SelectTrigger)
select_value = _unstyled(SelectValue)
select_icon = _unstyled(SelectIcon)
select_portal = _unstyled(SelectPortal)
select_positioner = _unstyled(SelectPositioner)
select_popup = _unstyled(SelectPopup)
select_item = _unstyled(SelectItem)
select_item_text = _unstyled(SelectItemText)

accordion_root = _unstyled(AccordionRoot)
accordion_item = _unstyled(AccordionItem)
accordion_header = _unstyled(AccordionHeader)
accordion_trigger = _unstyled(AccordionTrigger)
accordion_panel = _unstyled(AccordionPanel)
