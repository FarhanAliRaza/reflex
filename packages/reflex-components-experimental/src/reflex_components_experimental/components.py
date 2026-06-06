"""Experimental components: plain HTML elements styled with atomic Tailwind
utilities against Radix's exact design tokens (shipped in ``theme.css``).

Authored from Radix Themes' own component CSS, so the rendered box model,
typography and colour match Radix pixel-for-pixel (verified component-by-
component) while shipping a fraction of the CSS. User ``class_name`` overrides
win via :func:`cn` (tailwind-merge). Requires ``TailwindV4Plugin`` and
:class:`~reflex_components_experimental.plugin.ExperimentalThemePlugin`.
"""

from collections.abc import Callable

import reflex as rx
from reflex_components_experimental.utils import cn

# --- Button -----------------------------------------------------------------
# Mirrors Radix .rt-BaseButton / .rt-Button at default medium radius, scaling 1.

_BTN_BASE = (
    "inline-flex items-center justify-center shrink-0 align-top box-border "
    "relative select-none font-medium whitespace-nowrap border-0 "
    "cursor-[var(--cursor-button)] bg-transparent"
)

# non-ghost size -> (height, px, gap, font-size idx, radius idx)
_SIZES = {
    "1": ("--space-5", "--space-2", "--space-1", "1", "--radius-1"),
    "2": ("--space-6", "--space-3", "--space-2", "2", "--radius-2"),
    "3": ("--space-7", "--space-4", "--space-3", "3", "--radius-3"),
    "4": ("--space-8", "--space-5", "--space-3", "4", "--radius-4"),
}
# ghost size -> (px, py, gap, font-size idx, radius idx)
_GHOST_SIZES = {
    "1": ("--space-2", "var(--space-1)", "--space-1", "1", "--radius-1"),
    "2": ("--space-2", "var(--space-1)", "--space-1", "2", "--radius-2"),
    "3": ("--space-3", "calc(var(--space-1)*1.5)", "--space-2", "3", "--radius-3"),
    "4": ("--space-4", "var(--space-2)", "--space-2", "4", "--radius-4"),
}

_VARIANT_COLORS = {
    "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)] hover:bg-[var(--accent-10)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)] hover:bg-[var(--accent-a4)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a8)] text-[var(--accent-a11)] hover:bg-[var(--accent-a2)]",
    "surface": "bg-[var(--accent-surface)] shadow-[inset_0_0_0_1px_var(--accent-a7)] text-[var(--accent-a11)]",
    "ghost": "text-[var(--accent-a11)] hover:bg-[var(--accent-a3)]",
}


def _font(fs: str) -> str:
    return (
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})]"
    )


def _classes(size: str, variant: str) -> str:
    if variant == "ghost":
        px, py, gap, fs, rad = _GHOST_SIZES[size]
        box = (
            f"box-content font-normal px-[var({px})] py-[{py}] gap-[var({gap})] "
            f"-mx-[var({px})] -my-[{py}] h-fit "
            f"rounded-[max(var({rad}),var(--radius-full))]"
        )
    else:
        h, px, gap, fs, rad = _SIZES[size]
        box = (
            f"h-[var({h})] px-[var({px})] gap-[var({gap})] "
            f"rounded-[max(var({rad}),var(--radius-full))]"
        )
    return f"{_BTN_BASE} {_font(fs)} {box} {_VARIANT_COLORS[variant]}"


def button(
    *children,
    size: str = "2",
    variant: str = "solid",
    **props,
) -> rx.Component:
    """A Radix-faithful button.

    Args:
        *children: Button content.
        size: Radix size ("1"-"4").
        variant: solid/soft/outline/surface/ghost.
        **props: Extra props; ``class_name`` overrides win via cn.

    Returns:
        The button element.
    """
    props["class_name"] = cn(_classes(size, variant), props.pop("class_name", ""))
    return rx.el.button(*children, **props)


# --- Badge ------------------------------------------------------------------
# Mirrors Radix .rt-Badge.

_BADGE_BASE = (
    "inline-flex items-center shrink-0 whitespace-nowrap font-medium not-italic"
)
_BADGE_SIZES = {
    "1": (
        "text-[length:var(--font-size-1)] leading-[var(--line-height-1)] "
        "tracking-[var(--letter-spacing-1)] "
        "py-[calc(var(--space-1)*0.5)] px-[calc(var(--space-1)*1.5)] "
        "gap-[calc(var(--space-1)*1.5)] rounded-[max(var(--radius-1),var(--radius-full))]"
    ),
    "2": (
        "text-[length:var(--font-size-1)] leading-[var(--line-height-1)] "
        "tracking-[var(--letter-spacing-1)] py-[var(--space-1)] px-[var(--space-2)] "
        "gap-[calc(var(--space-1)*1.5)] rounded-[max(var(--radius-2),var(--radius-full))]"
    ),
    "3": (
        "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
        "tracking-[var(--letter-spacing-2)] py-[var(--space-1)] "
        "px-[calc(var(--space-2)*1.25)] gap-[var(--space-2)] "
        "rounded-[max(var(--radius-2),var(--radius-full))]"
    ),
}
_BADGE_VARIANTS = {
    "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)]",
    "surface": "bg-[var(--accent-surface)] shadow-[inset_0_0_0_1px_var(--accent-a6)] text-[var(--accent-a11)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a8)] text-[var(--accent-a11)]",
}


def badge(*children, size: str = "1", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful badge.

    Args:
        *children: Content.
        size: "1"-"3".
        variant: solid/soft/surface/outline.
        **props: Extra props.

    Returns:
        The badge element.
    """
    cls = f"{_BADGE_BASE} {_BADGE_SIZES[size]} {_BADGE_VARIANTS[variant]}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)


# --- Separator --------------------------------------------------------------
# Mirrors Radix .rt-Separator (horizontal).

_SEP_SIZE = {"1": "--space-4", "2": "--space-6", "3": "--space-9"}


def separator(size: str = "1", **props) -> rx.Component:
    """A Radix-faithful horizontal separator.

    Args:
        size: "1"-"3" (width).
        **props: Extra props.

    Returns:
        The separator element.
    """
    cls = f"block bg-[var(--accent-a6)] h-px w-[var({_SEP_SIZE[size]})]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


# --- Text -------------------------------------------------------------------
# Mirrors Radix .rt-Text.

_TEXT_WEIGHT = {"light": "300", "regular": "400", "medium": "500", "bold": "700"}


def text(*children, size: str = "3", weight: str = "regular", **props) -> rx.Component:
    """A Radix-faithful text span.

    Args:
        *children: Content.
        size: "1"-"9".
        weight: light/regular/medium/bold.
        **props: Extra props.

    Returns:
        The text element.
    """
    cls = (
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] font-[{_TEXT_WEIGHT[weight]}]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)


# --- Heading ----------------------------------------------------------------
# Mirrors Radix .rt-Heading (default weight bold).

_HEADING_BASE = "font-bold not-italic font-[family-name:var(--heading-font-family)]"


def heading(*children, size: str = "6", **props) -> rx.Component:
    """A Radix-faithful heading.

    Args:
        *children: Content.
        size: "1"-"9".
        **props: Extra props.

    Returns:
        The heading element.
    """
    cls = (
        f"{_HEADING_BASE} "
        f"text-[length:calc(var(--font-size-{size})*var(--heading-font-size-adjust))] "
        f"leading-[var(--heading-line-height-{size})] "
        f"tracking-[calc(var(--letter-spacing-{size})+var(--heading-letter-spacing))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.h1(*children, **props)


# --- Code (inline) ----------------------------------------------------------
# Mirrors Radix .rt-Code, default soft variant.

_CODE_BASE = (
    "font-[family-name:var(--code-font-family)] not-italic [font-weight:inherit] "
    "box-border h-fit rounded-[calc((0.5px+0.2em)*var(--radius-factor))] "
    "pt-[var(--code-padding-top)] pb-[var(--code-padding-bottom)] "
    "pl-[var(--code-padding-left)] pr-[var(--code-padding-right)]"
)
_CODE_VARIANTS = {
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)]",
    "solid": "bg-[var(--accent-a9)] text-[var(--accent-contrast)]",
    "outline": "shadow-[inset_0_0_0_max(1px,0.033em)_var(--accent-a8)] text-[var(--accent-a11)]",
}


def code(*children, size: str = "2", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful inline code element.

    Args:
        *children: Content.
        size: "1"-"9".
        variant: soft/solid/outline.
        **props: Extra props.

    Returns:
        The code element.
    """
    cls = (
        f"{_CODE_BASE} {_CODE_VARIANTS[variant]} "
        f"text-[length:calc(var(--font-size-{size})*var(--code-font-size-adjust)*0.95)] "
        f"leading-[var(--line-height-{size})] "
        f"tracking-[calc(var(--code-letter-spacing)+var(--letter-spacing-{size}))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.code(*children, **props)


# --- Inline formatting: Em / Strong / Quote ---------------------------------

_LS = "var(--letter-spacing,var(--default-letter-spacing))"


def _inline(
    tag_fn: Callable[..., rx.Component],
    prefix: str,
    *children,
    line_height: str | None = None,
    **props,
) -> rx.Component:
    cls = (
        f"font-[family-name:var(--{prefix}-font-family)] "
        f"text-[length:calc(var(--{prefix}-font-size-adjust)*1em)] "
        f"[font-style:var(--{prefix}-font-style)] [font-weight:var(--{prefix}-font-weight)] "
        f"tracking-[calc(var(--{prefix}-letter-spacing)+{_LS})]"
    )
    if line_height:
        cls += f" box-border leading-[{line_height}]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return tag_fn(*children, **props)


def em(*children, **props) -> rx.Component:
    """Radix-faithful emphasis (italic).

    Returns:
        The rendered component.
    """
    return _inline(rx.el.em, "em", *children, line_height="1.25", **props)


def strong(*children, **props) -> rx.Component:
    """Radix-faithful strong (bold).

    Returns:
        The rendered component.
    """
    return _inline(rx.el.strong, "strong", *children, **props)


def quote(*children, **props) -> rx.Component:
    """Radix-faithful inline quote.

    Returns:
        The rendered component.
    """
    return _inline(rx.el.q, "quote", *children, line_height="1.25", **props)


# --- Callout ----------------------------------------------------------------
# Mirrors Radix .rt-CalloutRoot.

_CALLOUT_BASE = (
    "box-border grid items-start justify-start text-left text-[var(--accent-a11)]"
)
_CALLOUT_SIZES = {
    "1": "gap-y-[var(--space-2)] gap-x-[var(--space-2)] p-[var(--space-3)] rounded-[var(--radius-3)]",
    "2": "gap-y-[var(--space-2)] gap-x-[var(--space-3)] p-[var(--space-4)] rounded-[var(--radius-4)]",
}
_CALLOUT_VARIANTS = {
    "soft": "bg-[var(--accent-a3)]",
    "surface": "shadow-[inset_0_0_0_1px_var(--accent-a6)] bg-[var(--accent-a2)]",
    "outline": "shadow-[inset_0_0_0_1px_var(--accent-a7)]",
}


def callout(*children, size: str = "1", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful callout root.

    Args:
        *children: Content.
        size: "1"-"2".
        variant: soft/surface/outline.
        **props: Extra props.

    Returns:
        The callout element.
    """
    cls = f"{_CALLOUT_BASE} {_CALLOUT_SIZES[size]} {_CALLOUT_VARIANTS[variant]}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    # Radix wraps callout content in size-2 text; match so the root sizes match.
    return rx.el.div(text(*children, size="2"), **props)


# --- Blockquote -------------------------------------------------------------
# Mirrors Radix .rt-Blockquote (border-left + padding + text sizing).

_BQ_BASE = (
    "box-border "
    "[border-left:max(var(--space-1),0.25em)_solid_var(--accent-a6)] "
    "pl-[min(var(--space-5),max(var(--space-3),0.5em))]"
)


def blockquote(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful blockquote.

    Args:
        *children: Content.
        size: "1"-"9" (text sizing).
        **props: Extra props.

    Returns:
        The blockquote element.
    """
    cls = (
        f"{_BQ_BASE} text-[length:var(--font-size-{size})] "
        f"leading-[var(--line-height-{size})] tracking-[var(--letter-spacing-{size})]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.blockquote(*children, **props)


# --- Card -------------------------------------------------------------------
# Mirrors Radix .rt-BaseCard / .rt-Card surface variant. Background lives on a
# ::before pseudo and the 1px ring on ::after, exactly like Radix, so the root
# element itself stays transparent (matching Radix's root computed styles).

_CARD_BASE = (
    "block relative overflow-hidden box-border not-italic text-start [contain:paint] "
    "font-normal font-[family-name:var(--default-font-family)] "
    "before:content-[''] before:absolute before:inset-0 before:-z-10 "
    "before:rounded-[calc(var(--radius-4)-var(--card-border-width))] "
    "before:bg-[var(--color-panel)] "
    "after:content-[''] after:absolute after:pointer-events-none "
    "after:inset-[var(--card-border-width)] "
    "after:rounded-[calc(var(--radius-4)-var(--card-border-width))] "
    "after:shadow-[var(--base-card-surface-box-shadow)]"
)
_CARD_SIZES = {
    "1": "p-[var(--space-3)] rounded-[var(--radius-4)]",
    "2": "p-[var(--space-4)] rounded-[var(--radius-4)]",
}


def card(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful surface card.

    Args:
        *children: Content.
        size: "1"-"2".
        **props: Extra props.

    Returns:
        The card element.
    """
    cls = f"{_CARD_BASE} {_CARD_SIZES[size]}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


# --- Avatar -----------------------------------------------------------------
# Mirrors Radix .rt-AvatarRoot (the fallback bg/color lives on a child).

_AVATAR_BASE = (
    "inline-flex items-center justify-center align-middle select-none shrink-0 "
    "relative overflow-hidden"
)
# size -> (avatar-size, radius idx, letter-spacing idx)
_AVATAR_SIZES = {
    "1": ("--space-5", "2", "1"),
    "2": ("--space-6", "2", "2"),
    "3": ("--space-7", "3", "3"),
    "4": ("--space-8", "3", "4"),
}


def avatar(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful avatar root.

    Args:
        *children: Fallback/content.
        size: "1"-"4".
        **props: Extra props.

    Returns:
        The avatar element.
    """
    asz, rad, ls = _AVATAR_SIZES[size]
    cls = (
        f"{_AVATAR_BASE} w-[var({asz})] h-[var({asz})] "
        f"tracking-[var(--letter-spacing-{ls})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)


# --- Spinner ----------------------------------------------------------------
# Mirrors Radix .rt-Spinner root (leaves are children).

_SPINNER_SIZE = {
    "1": "var(--space-3)",
    "2": "var(--space-4)",
    "3": "calc(1.25*var(--space-4))",
}


def spinner(size: str = "2", **props) -> rx.Component:
    """A Radix-faithful spinner root.

    Args:
        size: "1"-"3".
        **props: Extra props.

    Returns:
        The spinner element.
    """
    sz = _SPINNER_SIZE[size]
    cls = f"block relative opacity-[var(--spinner-opacity)] w-[{sz}] h-[{sz}]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(**props)


# --- Table cells ------------------------------------------------------------
# Mirrors Radix .rt-TableCell / .rt-TableColumnHeaderCell (scaling = 1).

_TABLE_SIZES = {
    "1": ("p-[var(--space-2)]", "36px", "2"),
    "2": ("p-[var(--space-3)]", "44px", "2"),
    "3": ("py-[var(--space-3)] px-[var(--space-4)]", "var(--space-8)", "3"),
}
_TABLE_CELL_BASE = (
    "box-border [vertical-align:inherit] text-left bg-transparent "
    "text-[var(--gray-12)] shadow-[inset_0_-1px_var(--gray-a5)]"
)


def _table_cell_classes(size: str, header: bool) -> str:
    pad, min_h, fs = _TABLE_SIZES[size]
    weight = "font-bold" if header else "font-normal"
    return (
        f"{_TABLE_CELL_BASE} {pad} h-[{min_h}] {weight} "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] "
        f"font-[family-name:var(--default-font-family)]"
    )


def table_cell(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful table body cell (<td>).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        _table_cell_classes(size, False), props.pop("class_name", "")
    )
    return rx.el.td(*children, **props)


def table_header_cell(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful table column header cell (<th>, bold).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        _table_cell_classes(size, True), props.pop("class_name", "")
    )
    return rx.el.th(*children, **props)


# --- DataList label / value (horizontal) ------------------------------------

_DL_FONT = (
    "text-[length:var(--font-size-2)] leading-[var(--line-height-2)] "
    "tracking-[var(--letter-spacing-2)] font-normal not-italic "
    "font-[family-name:var(--default-font-family)] text-start"
)


def data_list_label(*children, **props) -> rx.Component:
    """A Radix-faithful DataList label.

    Returns:
        The rendered component.
    """
    cls = f"flex min-w-[120px] text-[var(--gray-a11)] {_DL_FONT}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def data_list_value(*children, **props) -> rx.Component:
    """A Radix-faithful DataList value (non-edge horizontal item).

    Returns:
        The rendered component.
    """
    cls = f"flex min-w-0 mx-0 my-[-0.25em] text-[var(--gray-12)] {_DL_FONT}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.dd(*children, **props)


# --- Link -------------------------------------------------------------------

_LINK_DECORATION = (
    "[text-decoration-line:none] [text-decoration-style:solid] "
    "[text-decoration-thickness:min(2px,max(1px,0.05em))] "
    "[text-underline-offset:calc(0.025em_+_2px)] "
    "[text-decoration-color:color-mix(in_oklab,var(--accent-a5),var(--gray-a6))]"
)


def link(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful link (accent color, auto underline).

    Returns:
        The rendered component.
    """
    cls = (
        f"text-[var(--accent-a11)] text-start "
        f"text-[length:var(--font-size-{size})] leading-[var(--line-height-{size})] "
        f"tracking-[var(--letter-spacing-{size})] font-normal not-italic "
        f"font-[family-name:var(--default-font-family)] {_LINK_DECORATION}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    props.setdefault("href", "#")
    return rx.el.a(*children, **props)


# --- TextField --------------------------------------------------------------
# The MEASURED element is Radix's flex Root (not the inner input); a single
# input reproduces the Root box. text-indent insets text without changing
# measured padding. line-height inherited (1.5).

_TF_BASE = (
    "box-border flex items-stretch text-start not-italic "
    "font-[family-name:var(--default-font-family)] font-[400] "
    "leading-[1.5] appearance-none border-0 outline-0 m-0 [background-clip:content-box]"
)
_TF_SIZES = {
    "1": (
        "--space-5",
        "max(var(--radius-2),var(--radius-full))",
        "1",
        "calc(var(--space-1)*1.5-var(--tf-bw))",
    ),
    "2": (
        "--space-6",
        "max(var(--radius-2),var(--radius-full))",
        "2",
        "calc(var(--space-2)-var(--tf-bw))",
    ),
    "3": (
        "--space-7",
        "max(var(--radius-3),var(--radius-full))",
        "3",
        "calc(var(--space-3)-var(--tf-bw))",
    ),
}
_TF_VARIANTS = {
    "surface": (
        "1px",
        "bg-[var(--color-surface)]",
        "text-[var(--gray-12)]",
        "shadow-[inset_0_0_0_1px_var(--gray-a7)]",
    ),
    "soft": ("0px", "bg-[var(--accent-a3)]", "text-[var(--accent-12)]", ""),
}


def text_field(
    *children, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful text field (matches .rt-TextFieldRoot box model).

    Returns:
        The rendered component.
    """
    height, radius, fs, pad = _TF_SIZES[size]
    bw, bg, color, shadow = _TF_VARIANTS[variant]
    cls = (
        f"{_TF_BASE} [--tf-bw:{bw}] h-[var({height})] p-[var(--tf-bw)] rounded-[{radius}] "
        f"text-[length:var(--font-size-{fs})] tracking-[var(--letter-spacing-{fs})] "
        f"[text-indent:{pad}] {bg} {color} {shadow}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.input(**props)


# --- TextArea ---------------------------------------------------------------
# Root inherits typography (font-size-3/1.5/0) because per-size font is on the
# inner input, not the Root.

_TA_BASE = (
    "box-border flex flex-col text-start not-italic "
    "font-[family-name:var(--default-font-family)] font-[400] "
    "text-[length:var(--font-size-3)] leading-[1.5] tracking-[0em] "
    "resize-none appearance-none border-0 outline-0 m-0 overflow-hidden [background-clip:content-box]"
)
_TA_SIZES = {
    "1": ("var(--space-8)", "2"),
    "2": ("var(--space-9)", "2"),
    "3": ("80px", "3"),
}
_TA_VARIANTS = {
    "surface": (
        "1px",
        "bg-[var(--color-surface)]",
        "text-[var(--gray-12)]",
        "shadow-[inset_0_0_0_1px_var(--gray-a7)]",
    ),
    "soft": ("0px", "bg-[var(--accent-a3)]", "text-[var(--accent-12)]", ""),
}


def text_area(
    *children, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful text area (matches .rt-TextAreaRoot box model).

    Returns:
        The rendered component.
    """
    min_h, radius = _TA_SIZES[size]
    bw, bg, color, shadow = _TA_VARIANTS[variant]
    cls = f"{_TA_BASE} p-[{bw}] min-h-[{min_h}] rounded-[var(--radius-{radius})] {bg} {color} {shadow}"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    props.setdefault("rows", 1)  # let min-height win (match Radix root height)
    return rx.el.textarea(*children, **props)


# --- Tabs (TabsList + TabsTrigger) ------------------------------------------
_TABS_SIZES = {
    "1": ("1", "--space-6", "--space-1", "--space-1", "calc(var(--space-1)*0.5)", "1"),
    "2": ("2", "--space-7", "--space-2", "--space-2", "var(--space-1)", "2"),
}


def tabs_list(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful TabsList.

    Returns:
        The rendered component.
    """
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


def tabs_trigger(
    text: str, size: str = "2", active: bool = False, **props
) -> rx.Component:
    """A Radix-faithful TabsTrigger.

    Returns:
        The rendered component.
    """
    _fs, h, px, ipx, ipy, irad = _TABS_SIZES[size]
    color = "text-[var(--gray-12)]" if active else "text-[var(--gray-a11)]"
    before = (
        "before:content-[''] before:box-border before:absolute before:h-0.5 "
        "before:bottom-0 before:left-0 before:right-0 before:bg-[var(--accent-indicator)]"
        if active
        else ""
    )
    trigger_cls = (
        "flex items-center justify-center shrink-0 relative select-none box-border text-start "
        f"h-[var({h})] px-[var({px})] {color} {before}"
    )
    weight = "font-medium" if active else ""
    base_inner = (
        "flex items-center justify-center box-border "
        f"py-[{ipy}] px-[var({ipx})] rounded-[var(--radius-{irad})]"
    )
    # Like Radix: an in-flow medium-weight sizing copy drives the width (so the
    # tab doesn't reflow when activated), with the visible copy overlaid.
    # active/medium copies carry --tab-active-letter-spacing (-0.01em), which
    # tightens them; the sizing copy is always medium so width is stable.
    act_ls = "tracking-[-0.01em]" if active else ""
    sizing = rx.el.span(
        text, class_name=f"{base_inner} font-medium tracking-[-0.01em] invisible"
    )
    visible = rx.el.span(
        text,
        class_name=f"{base_inner} {weight} {act_ls} absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    props["class_name"] = cn(trigger_cls, props.pop("class_name", ""))
    return rx.el.button(sizing, visible, **props)


# --- SegmentedControl (Root + Item) -----------------------------------------
_SEG_SIZES = {
    "1": ("1", "--space-5", "--space-3", "1", "2"),
    "2": ("2", "--space-6", "--space-4", "2", "2"),
    "3": ("3", "--space-7", "--space-4", "3", "3"),
}


def segmented_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful SegmentedControl root.

    Returns:
        The rendered component.
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
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def segmented_item(
    text: str, size: str = "2", active: bool = False, **props
) -> rx.Component:
    """A Radix-faithful SegmentedControl item.

    Returns:
        The rendered component.
    """
    fs, _h, px, gap, rad = _SEG_SIZES[size]
    before = (
        "before:content-[''] before:absolute before:inset-px before:-z-10 "
        f"before:rounded-[max(0.5px,calc(max(var(--radius-{rad}),var(--radius-full))-1px))] "
        "before:bg-[var(--segmented-control-indicator-background-color)]"
        if active
        else ""
    )
    weight = "font-medium" if active else "font-normal"
    label_cls = (
        "box-border flex grow items-center justify-center relative "
        f"px-[var({px})] gap-[var(--space-{gap})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))] {before}"
    )
    fsz = f"text-[length:var(--font-size-{fs})]"
    # Like Radix: an in-flow medium + (-0.01em) sizing copy fixes the column
    # width so items don't reflow when activated; visible copy overlaid.
    sizing = rx.el.span(
        text, class_name=f"{fsz} font-medium tracking-[-0.01em] invisible"
    )
    vls = "tracking-[-0.01em]" if active else f"tracking-[var(--letter-spacing-{fs})]"
    visible = rx.el.span(
        text,
        class_name=f"{fsz} {weight} {vls} absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
    )
    props["class_name"] = cn(
        "flex items-stretch select-none", props.pop("class_name", "")
    )
    return rx.el.div(rx.el.span(sizing, visible, class_name=label_cls), **props)


# --- Switch / Checkbox / Radio (fixed states) -------------------------------
_SWITCH_SIZES = {
    "1": ("var(--space-4)", "max(var(--radius-1),var(--radius-thumb))"),
    "2": ("calc(var(--space-5)*5/6)", "max(var(--radius-2),var(--radius-thumb))"),
    "3": ("var(--space-5)", "max(var(--radius-2),var(--radius-thumb))"),
}


def switch(
    checked: bool = False, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful switch in a fixed checked/unchecked state.

    Returns:
        The rendered component.
    """
    height, radius = _SWITCH_SIZES[size]
    state = "checked" if checked else "unchecked"
    width = f"calc({height}*1.75)"
    thumb_size = f"calc({height}_-_1px*2)"
    translate_x = f"calc({width}_-_{height})"
    bg_pos = (
        "before:[background-position:0%]"
        if checked
        else "before:[background-position-x:100%]"
    )
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
    thumb_transform = f"[transform:translateX({translate_x})]" if checked else ""
    thumb_cls = (
        "absolute left-[1px] top-[1px] z-[1] bg-white "
        f"w-[{thumb_size}] h-[{thumb_size}] rounded-[calc({radius}_-_1px)] {thumb_transform}"
    )
    props["class_name"] = cn(root_cls, props.pop("class_name", ""))
    props.setdefault("custom_attrs", {})["data-state"] = state
    return rx.el.button(
        rx.el.span(class_name=thumb_cls, custom_attrs={"data-state": state}), **props
    )


_CHECKBOX_SIZES = {
    "1": ("calc(var(--space-4)*0.875)", "calc(var(--radius-1)*0.875)"),
    "2": ("var(--space-4)", "var(--radius-1)"),
    "3": ("calc(var(--space-4)*1.25)", "calc(var(--radius-1)*1.25)"),
}


def checkbox(
    checked: bool = False, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful checkbox in a fixed state.

    Returns:
        The rendered component.
    """
    csize, radius = _CHECKBOX_SIZES[size]
    state = "checked" if checked else "unchecked"
    before_bg = (
        "before:bg-[var(--accent-indicator)]"
        if checked
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


_RADIO_SIZES = {
    "1": "calc(var(--space-4)*0.875)",
    "2": "var(--space-4)",
    "3": "calc(var(--space-4)*1.25)",
}


def radio(
    checked: bool = False, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful single radio item in a fixed state.

    Returns:
        The rendered component.
    """
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
_SLIDER_TRACK = {
    "1": "calc(var(--space-2)*0.75)",
    "2": "var(--space-2)",
    "3": "calc(var(--space-2)*1.25)",
}
_SLIDER_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--slider-track-size)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def slider_track(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider track (surface).

    Returns:
        The rendered component.
    """
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] overflow-hidden relative grow h-[{h}] {_SLIDER_RADIUS} "
        "bg-[var(--gray-a3)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def slider_range(size: str = "2", *, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful slider range (surface).

    Returns:
        The rendered component.
    """
    h = _SLIDER_TRACK[size]
    cls = (
        f"[--slider-track-size:{h}] absolute h-full left-0 w-[{value}%] {_SLIDER_RADIUS} "
        "bg-[var(--accent-track)] shadow-[inset_0_0_0_1px_var(--gray-a5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


def slider_thumb(size: str = "2", **props) -> rx.Component:
    """A Radix-faithful slider thumb (surface).

    Returns:
        The rendered component.
    """
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


_PROGRESS_HEIGHT = {
    "1": "var(--space-1)",
    "2": "calc(var(--space-2)*0.75)",
    "3": "var(--space-2)",
}
_PROGRESS_RADIUS = (
    "rounded-[max(calc(var(--radius-factor)*var(--progress-height)/3),"
    "calc(var(--radius-factor)*var(--radius-thumb)))]"
)


def progress_root(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful progress track root (surface).

    Returns:
        The rendered component.
    """
    h = _PROGRESS_HEIGHT[size]
    cls = (
        f"[--progress-height:{h}] relative overflow-hidden grow h-[{h}] {_PROGRESS_RADIUS} "
        "bg-[var(--gray-a3)] after:content-[''] after:absolute after:inset-0 "
        "after:rounded-[inherit] after:shadow-[inset_0_0_0_1px_var(--gray-a4)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def progress_indicator(*, value: int = 50, **props) -> rx.Component:
    """A Radix-faithful progress indicator (surface).

    Returns:
        The rendered component.
    """
    cls = f"block h-full w-full origin-[left_center] [transform:scaleX(calc({value}/100))] bg-[var(--accent-track)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(**props)


_SCROLLBAR_SIZE = {"1": "var(--space-1)", "2": "var(--space-2)", "3": "var(--space-3)"}


def scroll_area_scrollbar(*children, size: str = "1", **props) -> rx.Component:
    """A Radix-faithful vertical scrollbar.

    Returns:
        The rendered component.
    """
    w = _SCROLLBAR_SIZE[size]
    cls = f"flex flex-col select-none w-[{w}] bg-[var(--gray-a3)] rounded-[max(var(--radius-1),var(--radius-full))]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def scroll_area_thumb(**props) -> rx.Component:
    """A Radix-faithful scrollbar thumb.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "relative grow rounded-[inherit] bg-[var(--gray-a8)]",
        props.pop("class_name", ""),
    )
    return rx.el.div(**props)


# --- Layout primitives ------------------------------------------------------
_FLEX_DIR = {
    "row": "flex-row",
    "column": "flex-col",
    "row-reverse": "flex-row-reverse",
    "column-reverse": "flex-col-reverse",
}
_ALIGN = {
    "start": "items-start",
    "center": "items-center",
    "end": "items-end",
    "baseline": "items-baseline",
    "stretch": "items-stretch",
}
_JUSTIFY = {
    "start": "justify-start",
    "center": "justify-center",
    "end": "justify-end",
    "between": "justify-between",
}


def box(*children, **props) -> rx.Component:
    """A Radix-faithful Box.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn("block box-border", props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def flex(
    *children,
    direction: str | None = None,
    gap: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Flex container.

    Returns:
        The rendered component.
    """
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


def grid(
    *children,
    columns: str | None = None,
    gap: str | None = None,
    align: str | None = None,
    justify: str | None = None,
    **props,
) -> rx.Component:
    """A Radix-faithful Grid container.

    Returns:
        The rendered component.
    """
    classes = [
        "grid box-border items-stretch justify-start",
        "[grid-template-rows:none]",
    ]
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


_CONTAINER_MAX = {
    "1": "--container-1",
    "2": "--container-2",
    "3": "--container-3",
    "4": "--container-4",
}


def container(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Container.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "flex box-border flex-col items-center shrink-0 grow p-[16px]",
        props.pop("class_name", ""),
    )
    inner = rx.el.div(
        *children, class_name=f"w-full max-w-[var({_CONTAINER_MAX[size]})]"
    )
    return rx.el.div(inner, **props)


_SECTION_PY = {"1": "--space-5", "2": "--space-7", "3": "--space-9"}


def section(*children, size: str = "3", **props) -> rx.Component:
    """A Radix-faithful Section.

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        f"box-border shrink-0 py-[var({_SECTION_PY[size]})]",
        props.pop("class_name", ""),
    )
    return rx.el.section(*children, **props)


def skeleton(*children, **props) -> rx.Component:
    """A Radix-faithful Skeleton.

    Returns:
        The rendered component.
    """
    cls = (
        "box-border [border-radius:var(--radius-1)] [background-image:none] [border:none] "
        "[box-shadow:none] text-transparent [outline:none] pointer-events-none select-none [background-clip:border-box] "
        "[animation:rt-skeleton-pulse_1000ms_infinite_alternate-reverse]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.span(*children, **props)


def inset(*children, **props) -> rx.Component:
    """A Radix-faithful Inset (side=all, standalone).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "box-border overflow-hidden m-0", props.pop("class_name", "")
    )
    return rx.el.div(*children, **props)


# --- Overlay content panels -------------------------------------------------
def tooltip_content(*children, **props) -> rx.Component:
    """A Radix-faithful tooltip content panel (inner text is size-1; panel font inherits).

    Returns:
        The rendered component.
    """
    cls = "box-border relative py-[var(--space-1)] px-[var(--space-2)] bg-[var(--gray-12)] rounded-[var(--radius-2)]"
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    # Block inner (like Radix's <p class=rt-Text size-1>) so the panel's strut
    # doesn't inflate the height; panel keeps inherited font-size/line-height.
    inner = rx.el.p(
        *children,
        class_name="m-0 text-[length:var(--font-size-1)] leading-[var(--line-height-1)]",
    )
    return rx.el.div(inner, **props)


def popover_content(*children, **props) -> rx.Component:
    """A Radix-faithful popover content panel (size 2).

    Returns:
        The rendered component.
    """
    cls = (
        "box-border relative overflow-auto outline-0 p-[var(--space-4)] rounded-[var(--radius-4)] "
        "bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def hovercard_content(*children, **props) -> rx.Component:
    """A Radix-faithful hover card content panel (size 2).

    Returns:
        The rendered component.
    """
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
    """A Radix-faithful Dialog content panel (size 3).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def alert_dialog_content(*children, **props) -> rx.Component:
    """A Radix-faithful AlertDialog content panel (size 3).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_DIALOG_CONTENT, props.pop("class_name", ""))
    return rx.el.div(*children, **props)


def accordion_trigger(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion trigger box.

    Returns:
        The rendered component.
    """
    cls = (
        "flex flex-1 justify-between items-center w-full m-0 bg-none border-none box-border "
        "px-[var(--space-4)] py-[var(--space-3)] text-[length:1.1em] leading-[1] text-[var(--accent-contrast)]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.button(*children, **props)


def accordion_item(*children, **props) -> rx.Component:
    """A Radix-faithful (classic) accordion item box (single/first+last).

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(
        "block overflow-hidden w-full box-border m-0 rounded-[var(--radius-4)]",
        props.pop("class_name", ""),
    )
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

    Returns:
        The rendered component.
    """
    props["class_name"] = cn(_MENU_CONTENT, props.pop("class_name", ""))
    return rx.el.div(
        rx.el.div(*children, class_name="flex flex-col p-[var(--space-2)]"), **props
    )


def menu_item(text: str, highlighted: bool = False, **props) -> rx.Component:
    """A Radix-faithful menu item (size 2).

    Returns:
        The rendered component.
    """
    cls = _MENU_ITEM + (
        " bg-[var(--accent-9)] text-[var(--accent-contrast)]" if highlighted else ""
    )
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


def select_trigger(
    text: str, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful select trigger button.

    Returns:
        The rendered component.
    """
    h, px, gap, fs, rad = _SELECT_TRIGGER_SIZES[size]
    cls = (
        f"{_SELECT_TRIGGER_BASE} h-[var({h})] pl-[var({px})] pr-[var({px})] gap-[{gap}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[max(var({rad}),var(--radius-full))] "
        f"{_SELECT_TRIGGER_VARIANTS[variant]}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    chevron = rx.el.span(
        class_name="w-[9px] h-[9px] shrink-0"
    )  # matches .rt-SelectIcon width
    return rx.el.button(rx.el.span(text), chevron, **props)


_SELECT_CONTENT = "flex flex-col overflow-hidden box-border bg-[var(--color-panel-solid)] shadow-[var(--shadow-5)]"
_SELECT_CONTENT_SIZES = {
    "1": ("--space-1", "--radius-3"),
    "2": ("--space-2", "--radius-4"),
    "3": ("--space-2", "--radius-4"),
}
_SELECT_ITEM_SIZES = {
    "1": ("--space-5", "calc(var(--space-5)/1.2)", "1", "--radius-1"),
    "2": ("--space-6", "var(--space-5)", "2", "--radius-2"),
    "3": ("--space-6", "var(--space-5)", "3", "--radius-2"),
}


def select_content(*children, size: str = "2", **props) -> rx.Component:
    """A Radix-faithful select content panel (solid).

    Returns:
        The rendered component.
    """
    pad, rad = _SELECT_CONTENT_SIZES[size]
    props["class_name"] = cn(
        f"{_SELECT_CONTENT} rounded-[var({rad})]", props.pop("class_name", "")
    )
    return rx.el.div(
        rx.el.div(*children, class_name=f"flex flex-col p-[var({pad})]"), **props
    )


def select_item(
    text: str,
    size: str = "2",
    variant: str = "solid",
    highlighted: bool = False,
    **props,
) -> rx.Component:
    """A Radix-faithful select item.

    Returns:
        The rendered component.
    """
    h, padx, fs, rad = _SELECT_ITEM_SIZES[size]
    cls = (
        "flex items-center box-border relative outline-none select-none "
        f"h-[var({h})] pl-[{padx}] pr-[{padx}] "
        f"text-[length:var(--font-size-{fs})] leading-[var(--line-height-{fs})] "
        f"tracking-[var(--letter-spacing-{fs})] rounded-[var({rad})]"
    )
    if highlighted:
        cls += (
            " bg-[var(--accent-9)] text-[var(--accent-contrast)]"
            if variant == "solid"
            else " bg-[var(--accent-a4)]"
        )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.div(rx.el.span(text), **props)
