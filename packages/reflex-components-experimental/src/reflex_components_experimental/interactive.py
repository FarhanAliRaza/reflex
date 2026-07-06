"""Accessible interactive components: Radix-token styling on Base UI behavior.

These mirror the visual-parity look of :mod:`reflex_components_experimental.components`
but are backed by Base UI headless parts, so they ship real ARIA semantics,
keyboard navigation and focus management. State styling that the static
components hard-coded (e.g. a checked switch) is expressed here as Base UI
``data-[checked]`` / ``data-[selected]`` / ``data-[highlighted]`` Tailwind
variants, so the look tracks live state automatically.

Simple controls keep a flat callable API (``switch``, ``checkbox``); compound
widgets are grouped namespaces of styled Base UI parts (``dialog.root``,
``menu.item``, ``select.trigger`` ...) that the caller composes.
"""

from __future__ import annotations

from types import SimpleNamespace

import reflex as rx
from reflex_components_experimental import baseui as b
from reflex_components_experimental.utils import merge_class_name


def _styled(part: type[b.BaseUI], default_cls: str):
    """Return a ``create`` that prepends ``default_cls`` under any override.

    Args:
        part: A Base UI part component class.
        default_cls: The token Tailwind classes to apply by default.

    Returns:
        A callable mirroring ``part.create`` with merged ``class_name``.
    """

    def create(*children, **props):
        merge_class_name(default_cls, props)
        return part.create(*children, **props)

    return create


# --- Switch -----------------------------------------------------------------
_SWITCH_SIZES = {
    "1": ("var(--space-4)", "max(var(--radius-1),var(--radius-thumb))"),
    "2": ("calc(var(--space-5)*5/6)", "max(var(--radius-2),var(--radius-thumb))"),
    "3": ("var(--space-5)", "max(var(--radius-2),var(--radius-thumb))"),
}


def switch(size: str = "2", **props) -> b.SwitchRoot:
    """An accessible Radix-faithful switch (Base UI ``role=switch``).

    Args:
        size: Radix size ("1"-"3").
        **props: Base UI Switch props (``checked``, ``default_checked``,
            ``on_checked_change``, ``disabled``, ...) plus ``class_name``.

    Returns:
        The switch root component (with its thumb).
    """
    height, radius = _SWITCH_SIZES[size]
    width = f"calc({height}*1.75)"
    thumb_size = f"calc({height}_-_1px*2)"
    translate_x = f"calc({width}_-_{height})"
    root_cls = (
        "relative inline-flex items-center align-top shrink-0 text-start "
        "cursor-pointer disabled:cursor-default "
        "focus-visible:outline-2 focus-visible:outline-offset-2 "
        "focus-visible:outline-[var(--focus-8)] "
        f"h-[{height}] before:content-[''] before:block "
        f"before:w-[{width}] before:h-[{height}] before:rounded-[{radius}] "
        "before:bg-no-repeat "
        f"before:[background-size:calc({width}*2_+_{height})_100%] "
        "before:bg-[var(--gray-a3)] "
        "before:[background-image:linear-gradient(to_right,var(--accent-track)_40%,transparent_60%)] "
        "data-[checked]:before:[background-position:0%] "
        "data-[unchecked]:before:[background-position-x:100%] "
        "data-[unchecked]:before:shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    thumb_cls = (
        "absolute left-[1px] top-[1px] z-[1] bg-white transition-transform "
        f"w-[{thumb_size}] h-[{thumb_size}] rounded-[calc({radius}_-_1px)] "
        f"data-[checked]:[transform:translateX({translate_x})]"
    )
    merge_class_name(root_cls, props)
    return b.SwitchRoot.create(b.SwitchThumb.create(class_name=thumb_cls), **props)


# --- Checkbox ---------------------------------------------------------------
_CHECKBOX_SIZES = {
    "1": ("calc(var(--space-4)*0.875)", "calc(var(--radius-1)*0.875)"),
    "2": ("var(--space-4)", "var(--radius-1)"),
    "3": ("calc(var(--space-4)*1.25)", "calc(var(--radius-1)*1.25)"),
}

_CHECK_SVG = (
    "M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5"
    "a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"
)


def checkbox(size: str = "2", **props) -> b.CheckboxRoot:
    """An accessible Radix-faithful checkbox (Base UI ``role=checkbox``).

    Args:
        size: Radix size ("1"-"3").
        **props: Base UI Checkbox props (``checked``, ``default_checked``,
            ``indeterminate``, ``on_checked_change``, ...) plus ``class_name``.

    Returns:
        The checkbox root component (with its indicator).
    """
    csize, radius = _CHECKBOX_SIZES[size]
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        "cursor-default p-0 border-0 "
        "focus-visible:outline-2 focus-visible:outline-offset-2 "
        "focus-visible:outline-[var(--focus-8)] "
        f"w-[{csize}] h-[{csize}] rounded-[{radius}] "
        "data-[unchecked]:bg-[var(--color-surface)] "
        "data-[unchecked]:shadow-[inset_0_0_0_1px_var(--gray-a7)] "
        "data-[checked]:bg-[var(--accent-indicator)] "
        "data-[indeterminate]:bg-[var(--accent-indicator)] "
        "text-[var(--accent-contrast)]"
    )
    indicator_cls = (
        "flex items-center justify-center w-full h-full data-[unchecked]:hidden"
    )
    check = rx.el.svg(
        rx.el.path(d=_CHECK_SVG),
        viewBox="0 0 16 16",
        fill="currentColor",
        class_name="w-[72%] h-[72%]",
    )
    merge_class_name(root_cls, props)
    return b.CheckboxRoot.create(
        b.CheckboxIndicator.create(check, class_name=indicator_cls), **props
    )


# --- Radio ------------------------------------------------------------------
_RADIO_SIZES = {
    "1": "calc(var(--space-4)*0.875)",
    "2": "var(--space-4)",
    "3": "calc(var(--space-4)*1.25)",
}


def radio_group(*children, **props) -> b.RadioGroup:
    """An accessible radio group (``role=radiogroup``, arrow-key navigation).

    Args:
        *children: ``radio`` items (and any labels/layout).
        **props: Base UI RadioGroup props (``value``, ``default_value``,
            ``on_value_change``, ...) plus ``class_name``.

    Returns:
        The radio group component.
    """
    merge_class_name("flex flex-col gap-2", props)
    return b.RadioGroup.create(*children, **props)


def radio(value: str, size: str = "2", **props) -> b.RadioRoot:
    """A single accessible radio item (``role=radio``) for use in a group.

    Args:
        value: The item's value within its group.
        size: Radix size ("1"-"3").
        **props: Base UI Radio props (``disabled``, ...) plus ``class_name``.

    Returns:
        The radio item component (with its indicator).
    """
    rsize = _RADIO_SIZES[size]
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        "cursor-default p-0 border-0 [border-radius:100%] "
        "focus-visible:outline-2 focus-visible:outline-offset-2 "
        "focus-visible:outline-[var(--focus-8)] "
        f"w-[{rsize}] h-[{rsize}] "
        "data-[unchecked]:bg-[var(--color-surface)] "
        "shadow-[inset_0_0_0_1px_var(--gray-a7)] "
        "data-[checked]:bg-[var(--accent-indicator)]"
    )
    indicator_cls = (
        "block [border-radius:100%] scale-[0.4] w-full h-full "
        "bg-[var(--accent-contrast)] data-[unchecked]:hidden"
    )
    merge_class_name(root_cls, props)
    return b.RadioRoot.create(
        b.RadioIndicator.create(class_name=indicator_cls), value=value, **props
    )


# --- Tabs -------------------------------------------------------------------
_TABS_SIZES = {
    "1": ("1", "--space-6", "--space-1", "--space-1", "calc(var(--space-1)*0.5)", "1"),
    "2": ("2", "--space-7", "--space-2", "--space-2", "var(--space-1)", "2"),
}


def _tabs_list(*children, size: str = "2", **props) -> rx.Component:
    """Styled Base UI TabsList.

    Args:
        *children: ``tabs.tab`` items.
        size: Radix size ("1"-"2").
        **props: Extra props.

    Returns:
        The tabs list component.
    """
    fs, *_ = _TABS_SIZES[size]
    cls = (
        "flex justify-start overflow-x-auto whitespace-nowrap not-italic relative "
        "font-[family-name:var(--default-font-family)] "
        "shadow-[inset_0_-1px_0_0_var(--gray-a5)] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})]"
    )
    merge_class_name(cls, props)
    return b.TabsList.create(*children, **props)


def _tabs_tab(text: str, value: str, size: str = "2", **props) -> b.TabsTab:
    """Styled Base UI Tab (selected state via ``data-[selected]``).

    Args:
        text: Tab label.
        value: Tab value.
        size: Radix size ("1"-"2").
        **props: Extra props.

    Returns:
        The tab component.
    """
    _fs, h, px, ipx, ipy, irad = _TABS_SIZES[size]
    trigger_cls = (
        "flex items-center justify-center shrink-0 relative select-none box-border text-start "
        "cursor-pointer bg-transparent border-0 "
        "text-[var(--gray-a11)] data-[selected]:text-[var(--gray-12)] "
        "before:content-[''] before:box-border before:absolute before:h-0.5 "
        "before:bottom-0 before:left-0 before:right-0 before:bg-[var(--accent-indicator)] "
        "before:opacity-0 data-[selected]:before:opacity-100 "
        f"h-[var({h})] px-[var({px})]"
    )
    base_inner = (
        "flex items-center justify-center box-border "
        f"py-[{ipy}] px-[var({ipx})] rounded-[var(--radius-{irad})]"
    )
    sizing = rx.el.span(
        text, class_name=f"{base_inner} font-medium tracking-[-0.01em] invisible"
    )
    visible = rx.el.span(
        text,
        class_name=f"{base_inner} group-data-[selected]:font-medium "
        "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    merge_class_name(f"group {trigger_cls}", props)
    return b.TabsTab.create(sizing, visible, value=value, **props)


tabs = SimpleNamespace(
    root=b.TabsRoot.create,
    list=_tabs_list,
    tab=_tabs_tab,
    panel=b.TabsPanel.create,
)


# --- SegmentedControl (ToggleGroup) -----------------------------------------
_SEG_SIZES = {
    "1": ("1", "--space-5", "--space-3", "1", "2"),
    "2": ("2", "--space-6", "--space-4", "2", "2"),
    "3": ("3", "--space-7", "--space-4", "3", "3"),
}


def _seg_root(*children, size: str = "2", **props) -> b.ToggleGroup:
    """Styled Base UI ToggleGroup as a segmented control root.

    Args:
        *children: ``segmented_control.item`` toggles.
        size: Radix size ("1"-"3").
        **props: Extra props.

    Returns:
        The toggle group component.
    """
    _, h, _px, _gap, rad = _SEG_SIZES[size]
    cls = (
        "inline-grid align-top [grid-auto-flow:column] [grid-auto-columns:1fr] "
        "items-stretch relative isolate text-center not-italic min-w-max "
        "font-[family-name:var(--default-font-family)] text-[var(--gray-12)] "
        "bg-[var(--color-surface)] "
        "[background-image:linear-gradient(var(--gray-a3),var(--gray-a3))] "
        f"h-[var({h})] rounded-[max(var(--radius-{rad}),var(--radius-full))]"
    )
    merge_class_name(cls, props)
    return b.ToggleGroup.create(*children, **props)


def _seg_item(text: str, value: str, size: str = "2", **props) -> b.Toggle:
    """Styled Base UI Toggle as a segmented control item.

    Args:
        text: Item label.
        value: Item value.
        size: Radix size ("1"-"3").
        **props: Extra props.

    Returns:
        The toggle component.
    """
    fs, _h, px, gap, rad = _SEG_SIZES[size]
    label_cls = (
        "box-border flex grow items-center justify-center relative "
        f"px-[var({px})] gap-[var(--space-{gap})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))] "
        "before:content-[''] before:absolute before:inset-px before:-z-10 "
        f"before:rounded-[max(0.5px,calc(max(var(--radius-{rad}),var(--radius-full))-1px))] "
        "before:bg-[var(--segmented-control-indicator-background-color)] "
        "before:opacity-0 group-data-[pressed]:before:opacity-100"
    )
    fsz = f"text-[length:var(--font-size-{fs})]"
    sizing = rx.el.span(
        text, class_name=f"{fsz} font-medium tracking-[-0.01em] invisible"
    )
    visible = rx.el.span(
        text,
        class_name=f"{fsz} font-normal group-data-[pressed]:font-medium "
        "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    merge_class_name(
        "group flex items-stretch select-none cursor-pointer bg-transparent border-0 p-0",
        props,
    )
    return b.Toggle.create(
        rx.el.span(sizing, visible, class_name=label_cls), value=value, **props
    )


segmented_control = SimpleNamespace(root=_seg_root, item=_seg_item)


# --- Slider -----------------------------------------------------------------
_SLIDER_TRACK = {
    "1": "calc(var(--space-2)*0.75)",
    "2": "var(--space-2)",
    "3": "calc(var(--space-2)*1.25)",
}
_SLIDER_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--slider-track-size)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def slider(size: str = "2", **props) -> b.SliderRoot:
    """An accessible Radix-faithful slider (arrow-key value changes).

    Args:
        size: Radix size ("1"-"3").
        **props: Base UI Slider props (``value``, ``default_value``, ``min``,
            ``max``, ``step``, ``on_value_change``, ...) plus ``class_name``.

    Returns:
        The slider root component (control + track + indicator + thumb).
    """
    h = _SLIDER_TRACK[size]
    track_cls = (
        f"[--slider-track-size:{h}] overflow-hidden relative grow h-[{h}] {_SLIDER_RADIUS} "
        "bg-[var(--gray-a3)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    indicator_cls = (
        f"[--slider-track-size:{h}] absolute h-full {_SLIDER_RADIUS} "
        "bg-[var(--accent-track)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    thumb_cls = (
        f"[--slider-track-size:{h}] block relative outline-0 "
        f"w-[calc({h}+var(--space-1))] h-[calc({h}+var(--space-1))] "
        "focus-visible:outline-2 focus-visible:outline-offset-2 "
        "focus-visible:outline-[var(--focus-8)] "
        "after:content-[''] after:absolute after:inset-[calc(-0.25*var(--slider-track-size))] "
        "after:bg-white after:rounded-[max(var(--radius-1),var(--radius-thumb))] "
        "after:shadow-[0_0_0_1px_var(--black-a4)]"
    )
    merge_class_name("relative flex items-center select-none touch-none w-full", props)
    return b.SliderRoot.create(
        b.SliderControl.create(
            b.SliderTrack.create(
                b.SliderIndicator.create(class_name=indicator_cls),
                b.SliderThumb.create(class_name=thumb_cls),
                class_name=track_cls,
            ),
            class_name="flex items-center w-full grow",
        ),
        **props,
    )


# --- Progress ---------------------------------------------------------------
_PROGRESS_HEIGHT = {
    "1": "var(--space-1)",
    "2": "calc(var(--space-2)*0.75)",
    "3": "var(--space-2)",
}
_PROGRESS_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--progress-height)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def progress(size: str = "2", value: int = 50, **props) -> b.ProgressRoot:
    """An accessible Radix-faithful progress bar (``role=progressbar``).

    Args:
        size: Radix size ("1"-"3").
        value: Current value (0-100).
        **props: Base UI Progress props (``min``, ``max``, ...) plus ``class_name``.

    Returns:
        The progress root component (track + indicator).
    """
    h = _PROGRESS_HEIGHT[size]
    track_cls = (
        f"[--progress-height:{h}] relative overflow-hidden block h-[{h}] w-full {_PROGRESS_RADIUS} "
        "bg-[var(--gray-a3)] after:content-[''] after:absolute after:inset-0 "
        "after:rounded-[inherit] after:shadow-[inset_0_0_0_1px_var(--gray-a4)]"
    )
    indicator_cls = "block h-full bg-[var(--accent-track)]"
    merge_class_name("block w-full", props)
    return b.ProgressRoot.create(
        b.ProgressTrack.create(
            b.ProgressIndicator.create(class_name=indicator_cls),
            class_name=track_cls,
        ),
        value=value,
        **props,
    )


# --- ScrollArea -------------------------------------------------------------
_SCROLLBAR_SIZE = {"1": "var(--space-1)", "2": "var(--space-2)", "3": "var(--space-3)"}


def scroll_area(*children, size: str = "1", **props) -> rx.Component:
    """An accessible Radix-faithful scroll area (keyboard-scrollable viewport).

    Args:
        *children: Scrollable content.
        size: Scrollbar size ("1"-"3").
        **props: Extra props plus ``class_name`` (applied to the root).

    Returns:
        The scroll area root component.
    """
    w = _SCROLLBAR_SIZE[size]
    scrollbar_cls = (
        f"flex select-none touch-none w-[{w}] bg-[var(--gray-a3)] "
        "rounded-[max(var(--radius-1),var(--radius-full))]"
    )
    thumb_cls = "relative grow rounded-[inherit] bg-[var(--gray-a8)]"
    merge_class_name("relative overflow-hidden", props)
    return b.ScrollAreaRoot.create(
        b.ScrollAreaViewport.create(
            *children, class_name="w-full h-full overscroll-contain"
        ),
        b.ScrollAreaScrollbar.create(
            b.ScrollAreaThumb.create(class_name=thumb_cls),
            orientation="vertical",
            class_name=scrollbar_cls,
        ),
        **props,
    )


# --- Overlay panel styling --------------------------------------------------
_BACKDROP = (
    "fixed inset-0 bg-[var(--color-overlay)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 "
    "transition-opacity duration-150"
)
_DIALOG_POPUP = (
    "box-border fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 "
    "overflow-auto outline-none font-[family-name:var(--default-font-family)] "
    "p-[var(--space-5)] rounded-[var(--radius-5)] bg-[var(--color-panel-solid)] "
    "shadow-[var(--shadow-6)] w-[600px] max-w-[calc(100vw-2rem)]"
)
_POPOVER_POPUP = (
    "box-border relative overflow-auto outline-0 p-[var(--space-4)] rounded-[var(--radius-4)] "
    "bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)] origin-[var(--transform-origin)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-150"
)
_HOVERCARD_POPUP = (
    "box-border relative overflow-auto p-[var(--space-4)] rounded-[var(--radius-4)] "
    "bg-[var(--color-panel-solid)] shadow-[var(--shadow-4)] origin-[var(--transform-origin)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-150"
)
_TOOLTIP_POPUP = (
    "box-border relative py-[var(--space-1)] px-[var(--space-2)] "
    "bg-[var(--gray-12)] text-[var(--gray-1)] rounded-[var(--radius-2)] "
    "text-[length:var(--font-size-1)] leading-[var(--line-height-1)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-150"
)
_MENU_POPUP = (
    "box-border overflow-hidden bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)] "
    "rounded-[var(--radius-4)] p-[var(--space-2)] outline-none origin-[var(--transform-origin)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-150"
)
_MENU_ITEM = (
    "flex items-center gap-[var(--space-2)] box-border relative outline-none select-none cursor-default "
    "h-[var(--space-6)] pl-[var(--space-3)] pr-[var(--space-3)] "
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] tracking-[var(--letter-spacing-2)] "
    "rounded-[var(--radius-2)] text-[var(--gray-12)] "
    "data-[highlighted]:bg-[var(--accent-9)] data-[highlighted]:text-[var(--accent-contrast)]"
)


# --- Dialog -----------------------------------------------------------------
def _overlay_dialog(
    parts: tuple[type[b.BaseUI], ...], popup_cls: str, *, backdrop: bool = True
):
    """Build a dialog-family namespace from a Base UI part bundle.

    Args:
        parts: Tuple of (Root, Trigger, Portal, Backdrop, Popup, Title,
            Description, Close) part classes.
        popup_cls: Popup panel Tailwind classes.
        backdrop: Whether to expose a styled backdrop.

    Returns:
        A namespace of styled dialog parts.
    """
    root, trigger, portal, backdrop_p, popup, title, desc, close = parts
    ns = SimpleNamespace(
        root=root.create,
        trigger=_styled(trigger, "outline-none"),
        portal=portal.create,
        popup=_styled(popup, popup_cls),
        title=_styled(
            title,
            "m-0 font-bold text-[length:var(--font-size-5)] text-[var(--gray-12)]",
        ),
        description=_styled(
            desc, "mt-2 text-[length:var(--font-size-2)] text-[var(--gray-a11)]"
        ),
        close=_styled(close, "outline-none"),
    )
    if backdrop:
        ns.backdrop = _styled(backdrop_p, _BACKDROP)
    return ns


dialog = _overlay_dialog(
    (
        b.DialogRoot,
        b.DialogTrigger,
        b.DialogPortal,
        b.DialogBackdrop,
        b.DialogPopup,
        b.DialogTitle,
        b.DialogDescription,
        b.DialogClose,
    ),
    _DIALOG_POPUP,
)

alert_dialog = _overlay_dialog(
    (
        b.AlertDialogRoot,
        b.AlertDialogTrigger,
        b.AlertDialogPortal,
        b.AlertDialogBackdrop,
        b.AlertDialogPopup,
        b.AlertDialogTitle,
        b.AlertDialogDescription,
        b.AlertDialogClose,
    ),
    _DIALOG_POPUP,
)


# --- Popover ----------------------------------------------------------------
popover = SimpleNamespace(
    root=b.PopoverRoot.create,
    trigger=_styled(b.PopoverTrigger, "outline-none"),
    portal=b.PopoverPortal.create,
    positioner=b.PopoverPositioner.create,
    popup=_styled(b.PopoverPopup, _POPOVER_POPUP),
    title=_styled(
        b.PopoverTitle,
        "m-0 font-bold text-[length:var(--font-size-3)] text-[var(--gray-12)]",
    ),
    description=_styled(
        b.PopoverDescription, "text-[length:var(--font-size-2)] text-[var(--gray-a11)]"
    ),
    close=_styled(b.PopoverClose, "outline-none"),
)


# --- HoverCard (PreviewCard) ------------------------------------------------
hover_card = SimpleNamespace(
    root=b.PreviewCardRoot.create,
    trigger=_styled(b.PreviewCardTrigger, "outline-none"),
    portal=b.PreviewCardPortal.create,
    positioner=b.PreviewCardPositioner.create,
    popup=_styled(b.PreviewCardPopup, _HOVERCARD_POPUP),
)


# --- Tooltip ----------------------------------------------------------------
tooltip = SimpleNamespace(
    provider=b.TooltipProvider.create,
    root=b.TooltipRoot.create,
    trigger=_styled(b.TooltipTrigger, "outline-none"),
    portal=b.TooltipPortal.create,
    positioner=b.TooltipPositioner.create,
    popup=_styled(b.TooltipPopup, _TOOLTIP_POPUP),
)


# --- Menu -------------------------------------------------------------------
menu = SimpleNamespace(
    root=b.MenuRoot.create,
    trigger=_styled(b.MenuTrigger, "outline-none"),
    portal=b.MenuPortal.create,
    positioner=b.MenuPositioner.create,
    popup=_styled(b.MenuPopup, _MENU_POPUP),
    item=_styled(b.MenuItem, _MENU_ITEM),
    group=b.MenuGroup.create,
    group_label=_styled(
        b.MenuGroupLabel,
        "px-[var(--space-3)] py-[var(--space-1)] text-[length:var(--font-size-1)] text-[var(--gray-a10)]",
    ),
)


# --- Select -----------------------------------------------------------------
_SELECT_TRIGGER_BASE = (
    "inline-flex items-center justify-between shrink-0 select-none align-top box-border cursor-default "
    "font-[family-name:var(--default-font-family)] font-[var(--font-weight-regular)] not-italic "
    "text-start text-[var(--gray-12)] bg-[var(--color-surface)] "
    "shadow-[inset_0_0_0_1px_var(--gray-a7)] "
    "focus-visible:outline-2 focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--focus-8)] "
    "h-[var(--space-6)] pl-[var(--space-3)] pr-[var(--space-3)] gap-[calc(var(--space-1)*1.5)] "
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
    "tracking-[var(--letter-spacing-2)] rounded-[max(var(--radius-2),var(--radius-full))]"
)
_SELECT_POPUP = (
    "flex flex-col overflow-hidden box-border bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)] "
    "rounded-[var(--radius-4)] p-[var(--space-2)] outline-none origin-[var(--transform-origin)] "
    "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-150"
)
_SELECT_ITEM = (
    "flex items-center box-border relative outline-none select-none cursor-default "
    "h-[var(--space-6)] pl-[var(--space-5)] pr-[var(--space-5)] "
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
    "tracking-[var(--letter-spacing-2)] rounded-[var(--radius-2)] text-[var(--gray-12)] "
    "data-[highlighted]:bg-[var(--accent-9)] data-[highlighted]:text-[var(--accent-contrast)]"
)


def _select_trigger(*children, **props) -> rx.Component:
    """Styled Base UI Select trigger with a chevron icon.

    Args:
        *children: Trigger content (typically a ``select.value``).
        **props: Extra props plus ``class_name``.

    Returns:
        The select trigger component.
    """
    merge_class_name(_SELECT_TRIGGER_BASE, props)
    icon = b.SelectIcon.create(
        rx.el.svg(
            rx.el.path(
                d="M4.5 6L8 9.5L11.5 6",
                stroke="currentColor",
                fill="none",
                stroke_width="1.5",
            ),
            viewBox="0 0 16 16",
            class_name="w-[9px] h-[9px] shrink-0",
        )
    )
    return b.SelectTrigger.create(*children, icon, **props)


select = SimpleNamespace(
    root=b.SelectRoot.create,
    trigger=_select_trigger,
    value=b.SelectValue.create,
    portal=b.SelectPortal.create,
    positioner=b.SelectPositioner.create,
    popup=_styled(b.SelectPopup, _SELECT_POPUP),
    item=_styled(b.SelectItem, _SELECT_ITEM),
    item_text=b.SelectItemText.create,
)


# --- Accordion --------------------------------------------------------------
def _accordion_trigger(*children, **props) -> rx.Component:
    """Styled Base UI Accordion header+trigger.

    Args:
        *children: Trigger content.
        **props: Extra props plus ``class_name``.

    Returns:
        The accordion header wrapping its trigger.
    """
    cls = (
        "flex flex-1 justify-between items-center w-full m-0 bg-none border-none box-border cursor-pointer "
        "px-[var(--space-4)] py-[var(--space-3)] text-[length:1.1em] leading-[1] text-[var(--accent-contrast)] "
        "outline-none focus-visible:outline-2 focus-visible:outline-[var(--focus-8)]"
    )
    merge_class_name(cls, props)
    return b.AccordionHeader.create(b.AccordionTrigger.create(*children, **props))


accordion = SimpleNamespace(
    root=_styled(b.AccordionRoot, "flex flex-col w-full"),
    item=_styled(
        b.AccordionItem,
        "block overflow-hidden w-full box-border m-0 rounded-[var(--radius-4)]",
    ),
    trigger=_accordion_trigger,
    panel=_styled(
        b.AccordionPanel, "overflow-hidden px-[var(--space-4)] py-[var(--space-3)]"
    ),
)
