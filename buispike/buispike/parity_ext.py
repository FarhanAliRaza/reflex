"""Parity components (extended set) authored by parallel subagents.

Each function mirrors a Radix Themes component's exact computed styling using
Tailwind arbitrary values against the tokens in ``assets/theme.css``. Verified
by ``diff.py``. Re-exported from ``parity.py`` so they are reachable as
``P.<name>`` in the harness.
"""

import reflex as rx

from buispike.bui import cn

# --- Tabs (TabsList + TabsTrigger) ------------------------------------------
_TABS_SIZES = {
    "1": ("1", "--space-6", "--space-1", "--space-1", "calc(var(--space-1)*0.5)", "1"),
    "2": ("2", "--space-7", "--space-2", "--space-2", "var(--space-1)", "2"),
}


def tabs_list(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful TabsList."""
    fs, *_ = _TABS_SIZES[size]
    cls = (
        "flex justify-start overflow-x-auto whitespace-nowrap not-italic "
        "font-[family-name:var(--default-font-family)] "
        "shadow-[inset_0_-1px_0_0_var(--gray-a5)] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def tabs_trigger(text: str, size: str = "2", active: bool = False, **props) -> rx.Component:
    """A Radix-faithful TabsTrigger."""
    fs, h, px, ipx, ipy, irad = _TABS_SIZES[size]
    color = "text-[var(--gray-12)]" if active else "text-[var(--gray-a11)]"
    before = (
        "before:content-[''] before:box-border before:absolute before:h-0.5 "
        "before:bottom-0 before:left-0 before:right-0 before:bg-[var(--accent-indicator)]"
        if active else ""
    )
    trigger_cls = (
        "flex items-center justify-center shrink-0 relative select-none box-border text-start "
        f"h-[var({h})] px-[var({px})] {color} {before}"
    )
    inner_type = "font-medium" if active else ""
    inner_cls = (
        "flex items-center justify-center box-border "
        f"py-[{ipy}] px-[var({ipx})] rounded-[var(--radius-{irad})] {inner_type}"
    )
    props["class_name"] = cn(trigger_cls, props.pop("class_name", ""))
    return rx.el.button(rx.el.span(text, class_name=inner_cls), **props)


# --- SegmentedControl (Root + Item) -----------------------------------------
_SEG_SIZES = {
    "1": ("1", "--space-5", "--space-3", "1", "2"),
    "2": ("2", "--space-6", "--space-4", "2", "2"),
    "3": ("3", "--space-7", "--space-4", "3", "3"),
}


def segmented_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful SegmentedControl root."""
    _, h, _px, _gap, rad = _SEG_SIZES[size]
    cls = (
        "inline-grid align-top [grid-auto-flow:column] [grid-auto-columns:1fr] "
        "items-stretch relative isolate text-center not-italic min-w-max "
        "font-[family-name:var(--default-font-family)] text-[var(--gray-12)] "
        "bg-[var(--color-surface)] "
        "[background-image:linear-gradient(var(--gray-a3),var(--gray-a3))] "
        f"h-[var({h})] rounded-[max(var(--radius-{rad}),var(--radius-full))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def segmented_item(text: str, size: str = "2", active: bool = False, **props) -> rx.Component:
    """A Radix-faithful SegmentedControl item."""
    fs, _h, px, gap, rad = _SEG_SIZES[size]
    before = (
        "before:content-[''] before:absolute before:inset-px before:-z-10 "
        f"before:rounded-[max(0.5px,calc(max(var(--radius-{rad}),var(--radius-full))-1px))] "
        "before:bg-[var(--segmented-control-indicator-background-color)]"
        if active else ""
    )
    weight = "font-medium" if active else "font-normal"
    label_cls = (
        "box-border flex grow items-center justify-center relative "
        f"px-[var({px})] gap-[var(--space-{gap})] {weight} "
        f"text-[length:var(--font-size-{fs})] tracking-[var(--letter-spacing-{fs})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))] {before}"
    )
    props["class_name"] = cn("flex items-stretch select-none", props.pop("class_name", ""))
    return rx.el.div(rx.el.span(text, class_name=label_cls), **props)


# --- Switch / Checkbox / Radio (fixed states) -------------------------------
_SWITCH_SIZES = {
    "1": ("var(--space-4)", "max(var(--radius-1),var(--radius-thumb))"),
    "2": ("calc(var(--space-5)*5/6)", "max(var(--radius-2),var(--radius-thumb))"),
    "3": ("var(--space-5)", "max(var(--radius-2),var(--radius-thumb))"),
}


def switch(checked: bool = False, size: str = "2", variant: str = "surface", **props) -> rx.Component:
    """A Radix-faithful switch in a fixed checked/unchecked state."""
    height, radius = _SWITCH_SIZES[size]
    state = "checked" if checked else "unchecked"
    width = f"calc({height}*1.75)"
    thumb_size = f"calc({height} - 1px*2)"
    translate_x = f"calc({width} - {height})"
    bg_pos = "before:[background-position:0%]" if checked else "before:[background-position-x:100%]"
    root_cls = (
        "relative inline-flex items-center align-top shrink-0 text-start "
        f"h-[{height}] before:content-[''] before:block "
        f"before:w-[{width}] before:h-[{height}] before:rounded-[{radius}] "
        "before:bg-no-repeat "
        f"before:[background-size:calc({width}*2_+_{height})_100%] "
        "before:bg-[var(--gray-a3)] "
        "before:[background-image:linear-gradient(to_right,var(--accent-track)_40%,transparent_60%)] "
        f"{bg_pos}"
        + ("" if checked else " before:shadow-[inset_0_0_0_1px_var(--gray-a5)]")
    )
    thumb_transform = f"translate-x-[{translate_x}]" if checked else ""
    thumb_cls = (
        "absolute left-[1px] bg-white "
        f"w-[{thumb_size}] h-[{thumb_size}] rounded-[calc({radius} - 1px)] {thumb_transform}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(rx.el.span(class_name=thumb_cls, custom_attrs={"data-state": state}), **props)


_CHECKBOX_SIZES = {
    "1": ("calc(var(--space-4)*0.875)", "calc(var(--radius-1)*0.875)"),
    "2": ("var(--space-4)", "var(--radius-1)"),
    "3": ("calc(var(--space-4)*1.25)", "calc(var(--radius-1)*1.25)"),
}


def checkbox(checked: bool = False, size: str = "2", variant: str = "surface", **props) -> rx.Component:
    """A Radix-faithful checkbox in a fixed state."""
    csize, radius = _CHECKBOX_SIZES[size]
    state = "checked" if checked else "unchecked"
    before_bg = (
        "before:bg-[var(--accent-indicator)]" if checked
        else "before:bg-[var(--color-surface)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
    )
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] h-[var(--line-height-{size})] "
        f"before:content-[''] before:block "
        f"before:w-[{csize}] before:h-[{csize}] before:rounded-[{radius}] {before_bg}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(**props)


_RADIO_SIZES = {"1": "calc(var(--space-4)*0.875)", "2": "var(--space-4)", "3": "calc(var(--space-4)*1.25)"}


def radio(checked: bool = False, size: str = "2", variant: str = "surface", **props) -> rx.Component:
    """A Radix-faithful single radio item in a fixed state."""
    rsize = _RADIO_SIZES[size]
    state = "checked" if checked else "unchecked"
    if checked:
        before_bg = "before:bg-[var(--accent-indicator)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
        after_cls = (
            "after:content-[''] after:pointer-events-none after:absolute "
            f"after:w-[{rsize}] after:h-[{rsize}] after:[border-radius:100%] "
            "after:scale-[0.4] after:bg-[var(--accent-contrast)]"
        )
    else:
        before_bg = "before:bg-[var(--color-surface)] before:shadow-[inset_0_0_0_1px_var(--gray-a7)]"
        after_cls = ""
    root_cls = (
        "relative flex items-center justify-center align-top shrink-0 text-start "
        f"h-[{rsize}] before:content-[''] before:block "
        f"before:w-[{rsize}] before:h-[{rsize}] before:[border-radius:100%] {before_bg} {after_cls}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(**props)


# --- Slider / Progress / ScrollArea -----------------------------------------
_SLIDER_TRACK = {"1": "calc(var(--space-2)*0.75)", "2": "var(--space-2)", "3": "calc(var(--space-2)*1.25)"}
_SLIDER_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--slider-track-size)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def slider_track(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider track (surface)."""
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] overflow-hidden relative grow h-[{h}] {_SLIDER_RADIUS} "
        "bg-[var(--gray-a3)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def slider_range(size: str = "2", *, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful slider range (surface)."""
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] absolute h-full left-0 w-[{value}%] {_SLIDER_RADIUS} "
        "bg-[var(--accent-track)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


def slider_thumb(size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider thumb (surface)."""
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] block relative outline-0 "
        f"w-[calc({h}+var(--space-1))] h-[calc({h}+var(--space-1))] "
        "after:content-[''] after:absolute after:inset-[calc(-0.25*var(--slider-track-size))] "
        "after:bg-white after:rounded-[max(var(--radius-1),var(--radius-thumb))] "
        "after:shadow-[0_0_0_1px_var(--black-a4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(**props)


_PROGRESS_HEIGHT = {"1": "var(--space-1)", "2": "calc(var(--space-2)*0.75)", "3": "var(--space-2)"}
_PROGRESS_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--progress-height)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def progress_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful progress track root (surface)."""
    h = _PROGRESS_HEIGHT[size]
    cls = (
        f"[--progress-height:{h}] relative overflow-hidden grow h-[{h}] {_PROGRESS_RADIUS} "
        "bg-[var(--gray-a3)] after:content-[''] after:absolute after:inset-0 "
        "after:rounded-[inherit] after:shadow-[inset_0_0_0_1px_var(--gray-a4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def progress_indicator(*, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful progress indicator (surface)."""
    cls = f"block h-full w-full origin-[left_center] [transform:scaleX(calc({value}/100))] bg-[var(--accent-track)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


_SCROLLBAR_SIZE = {"1": "var(--space-1)", "2": "var(--space-2)", "3": "var(--space-3)"}


def scroll_area_scrollbar(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful vertical scrollbar."""
    w = _SCROLLBAR_SIZE[size]
    cls = f"flex flex-col select-none w-[{w}] bg-[var(--gray-a3)] rounded-[max(var(--radius-1),var(--radius-full))]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def scroll_area_thumb(**props) -> rx.Component:
    """A Radix-faithful scrollbar thumb."""
    props["class_name"] = cn("relative grow rounded-[inherit] bg-[var(--gray-a8)]", props.pop("class_name", ""))
    return rx.el.div(**props)


# --- Layout primitives ------------------------------------------------------
_FLEX_DIR = {"row": "flex-row", "column": "flex-col", "row-reverse": "flex-row-reverse", "column-reverse": "flex-col-reverse"}
_ALIGN = {"start": "items-start", "center": "items-center", "end": "items-end", "baseline": "items-baseline", "stretch": "items-stretch"}
_JUSTIFY = {"start": "justify-start", "center": "justify-center", "end": "justify-end", "between": "justify-between"}


def box(*children, **props) -> rx.Component:
    """A Radix-faithful Box."""
    props["class_name"] = cn("block box-border", props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def flex(*children, direction=None, gap=None, align=None, justify=None, **props) -> rx.Component:
    """A Radix-faithful Flex container."""
    classes = ["flex box-border justify-start"]
    if direction:
        classes.append(_FLEX_DIR[direction])
    if gap is not None:
        classes.append(f"gap-[var(--space-{gap})]")
    if align:
        classes.append(_ALIGN[align])
    if justify:
        classes.append(_JUSTIFY[justify])
    props["class_name"] = cn(" ".join(classes), props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def grid(*children, columns=None, gap=None, align=None, justify=None, **props) -> rx.Component:
    """A Radix-faithful Grid container."""
    classes = ["grid box-border items-stretch justify-start", "[grid-template-rows:none]"]
    if columns and columns != "1":
        classes.append(f"[grid-template-columns:repeat({columns},minmax(0,1fr))]")
    else:
        classes.append("[grid-template-columns:minmax(0,1fr)]")
    if gap is not None:
        classes.append(f"gap-[var(--space-{gap})]")
    if align:
        classes.append(_ALIGN[align])
    if justify:
        classes.append(_JUSTIFY[justify])
    props["class_name"] = cn(" ".join(classes), props.pop("class_name", ""))
    return rx.el.div(*children, **props)


_CONTAINER_MAX = {"1": "--container-1", "2": "--container-2", "3": "--container-3", "4": "--container-4"}


def container(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Container."""
    props["class_name"] = cn("flex box-border flex-col items-center shrink-0 grow p-[16px]", props.pop("class_name", ""))
    inner = rx.el.div(*children, class_name=f"w-full max-w-[var({_CONTAINER_MAX[size]})]")
    return rx.el.div(inner, **props)


_SECTION_PY = {"1": "--space-5", "2": "--space-7", "3": "--space-9"}


def section(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Section."""
    props["class_name"] = cn(f"box-border shrink-0 py-[var({_SECTION_PY[size]})]", props.pop("class_name", ""))
    return rx.el.section(*children, **props)


def skeleton(*children, **props) -> rx.Component:
    """A Radix-faithful Skeleton."""
    cls = (
        "box-border [border-radius:var(--radius-1)] [background-image:none] [border:none] "
        "[box-shadow:none] text-transparent [outline:none] pointer-events-none select-none "
        "bg-[var(--gray-a3)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)


def inset(*children, **props) -> rx.Component:
    """A Radix-faithful Inset (side=all, standalone)."""
    props["class_name"] = cn("box-border overflow-hidden m-0", props.pop("class_name", ""))
    return rx.el.div(*children, **props)


# --- Overlay content panels -------------------------------------------------
def tooltip_content(*children, **props) -> rx.Component:
    """A Radix-faithful tooltip content panel (inner text is size-1; panel font inherits)."""
    cls = "box-border relative py-[var(--space-1)] px-[var(--space-2)] bg-[var(--gray-12)] rounded-[var(--radius-2)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    # Block inner (like Radix's <p class=rt-Text size-1>) so the panel's strut
    # doesn't inflate the height; panel keeps inherited font-size/line-height.
    inner = rx.el.p(*children, class_name="m-0 text-[length:var(--font-size-1)] leading-[var(--line-height-1)]")
    return rx.el.div(inner, **props)


def popover_content(*children, **props) -> rx.Component:
    """A Radix-faithful popover content panel (size 2)."""
    cls = (
        "box-border relative overflow-auto outline-0 p-[var(--space-4)] rounded-[var(--radius-4)] "
        "bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def hovercard_content(*children, **props) -> rx.Component:
    """A Radix-faithful hover card content panel (size 2)."""
    cls = (
        "box-border relative overflow-auto p-[var(--space-4)] rounded-[var(--radius-4)] "
        "bg-[var(--color-panel-solid)] shadow-[var(--shadow-4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


# --- Dialog / AlertDialog / Accordion ---------------------------------------
_DIALOG_CONTENT = (
    "box-border relative overflow-auto outline-none m-auto font-[family-name:var(--default-font-family)] "
    "p-[var(--space-5)] rounded-[var(--radius-5)] bg-[var(--color-panel-solid)] shadow-[var(--shadow-6)] "
    "w-[600px] max-w-[600px]"
)


def dialog_content(*children, **props) -> rx.Component:
    """A Radix-faithful Dialog content panel (size 3)."""
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def alert_dialog_content(*children, **props) -> rx.Component:
    """A Radix-faithful AlertDialog content panel (size 3)."""
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def accordion_trigger(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion trigger box."""
    cls = (
        "flex flex-1 justify-between items-center w-full m-0 bg-none border-none box-border "
        "px-[var(--space-4)] py-[var(--space-3)] text-[length:1.1em] leading-[1] text-[var(--accent-contrast)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.button(*children, **props)


def accordion_item(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion item box (single/first+last)."""
    props["class_name"] = cn("block overflow-hidden w-full box-border m-0 rounded-[var(--radius-4)]", props.pop("class_name", ""))
    return rx.el.div(*children, **props)


# --- DropdownMenu / Select --------------------------------------------------
_MENU_CONTENT = (
    "flex flex-col box-border overflow-hidden bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)] "
    "rounded-[var(--radius-4)]"
)
_MENU_ITEM = (
    "flex items-center gap-[var(--space-2)] box-border relative outline-none select-none "
    "h-[var(--space-6)] pl-[var(--space-3)] pr-[var(--space-3)] "
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] tracking-[var(--letter-spacing-2)] "
    "rounded-[var(--radius-2)] text-[var(--gray-12)]"
)


def menu_content(*children, **props) -> rx.Component:
    """A Radix-faithful dropdown/context menu content panel (size 2, solid).

    Radix nests a padded viewport inside the (zero-padding) content; mirror that
    so the content box size matches.
    """
    props["class_name"] = cn(_MENU_CONTENT, props.pop("class_name", ""))
    return rx.el.div(rx.el.div(*children, class_name="flex flex-col p-[var(--space-2)]"), **props)


def menu_item(text: str, highlighted: bool = False, **props) -> rx.Component:
    """A Radix-faithful menu item (size 2)."""
    cls = _MENU_ITEM + (" bg-[var(--accent-9)] text-[var(--accent-contrast)]" if highlighted else "")
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(text, **props)


_SELECT_TRIGGER_BASE = (
    "inline-flex items-center justify-between shrink-0 select-none align-top box-border "
    "font-[family-name:var(--default-font-family)] font-[var(--font-weight-regular)] not-italic "
    "text-start text-[var(--gray-12)]"
)
_SELECT_TRIGGER_SIZES = {
    "1": ("--space-5", "--space-2", "var(--space-1)", "1", "--radius-1"),
    "2": ("--space-6", "--space-3", "calc(var(--space-1)*1.5)", "2", "--radius-2"),
    "3": ("--space-7", "--space-4", "var(--space-2)", "3", "--radius-3"),
}
_SELECT_TRIGGER_VARIANTS = {
    "surface": "bg-[var(--color-surface)] text-[var(--gray-12)] shadow-[inset_0_0_0_1px_var(--gray-a7)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-12)]",
}


def select_trigger(text: str, size: str = "2", variant: str = "surface", **props) -> rx.Component:
    """A Radix-faithful select trigger button."""
    h, px, gap, fs, rad = _SELECT_TRIGGER_SIZES[size]
    cls = (
        f"{_SELECT_TRIGGER_BASE} h-[var({h})] pl-[var({px})] pr-[var({px})] gap-[{gap}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[max(var({rad}),var(--radius-full))] "
        f"{_SELECT_TRIGGER_VARIANTS[variant]}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.button(rx.el.span(text), **props)


_SELECT_CONTENT = "flex flex-col overflow-hidden box-border bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)]"
_SELECT_CONTENT_SIZES = {"1": ("--space-1", "--radius-3"), "2": ("--space-2", "--radius-4"), "3": ("--space-2", "--radius-4")}
_SELECT_ITEM_SIZES = {
    "1": ("--space-5", "calc(var(--space-5)/1.2)", "1", "--radius-1"),
    "2": ("--space-6", "var(--space-5)", "2", "--radius-2"),
    "3": ("--space-6", "var(--space-5)", "3", "--radius-2"),
}


def select_content(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful select content panel (solid)."""
    pad, rad = _SELECT_CONTENT_SIZES[size]
    props["class_name"] = cn(f"{_SELECT_CONTENT} rounded-[var({rad})]", props.pop("class_name", ""))
    return rx.el.div(rx.el.div(*children, class_name=f"flex flex-col p-[var({pad})]"), **props)


def select_item(text: str, size: str = "2", variant: str = "solid", highlighted: bool = False, **props) -> rx.Component:
    """A Radix-faithful select item."""
    h, padx, fs, rad = _SELECT_ITEM_SIZES[size]
    cls = (
        "flex items-center box-border relative outline-none select-none "
        f"h-[var({h})] pl-[{padx}] pr-[{padx}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[var({rad})]"
    )
    if highlighted:
        cls += " bg-[var(--accent-9)] text-[var(--accent-contrast)]" if variant == "solid" else " bg-[var(--accent-a4)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(rx.el.span(text), **props)
