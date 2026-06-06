"""Parity components: Base UI / plain elements styled to match Radix Themes.

Each component is authored against the *exact* Radix tokens shipped in
``assets/theme.css`` (space, font-size, radius, accent scales), so the visual
result matches Radix by construction. Verified by pixel-diff (``diff.py``).
"""

import reflex as rx

from buispike.bui import cn

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

_BADGE_BASE = "inline-flex items-center shrink-0 whitespace-nowrap font-medium not-italic"
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

_HEADING_BASE = (
    "font-bold not-italic font-[family-name:var(--heading-font-family)]"
)


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


def _inline(tag_fn, prefix, *children, line_height=None, **props):
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
    """Radix-faithful emphasis (italic)."""
    return _inline(rx.el.em, "em", *children, line_height="1.25", **props)


def strong(*children, **props) -> rx.Component:
    """Radix-faithful strong (bold)."""
    return _inline(rx.el.strong, "strong", *children, **props)


def quote(*children, **props) -> rx.Component:
    """Radix-faithful inline quote."""
    return _inline(rx.el.q, "quote", *children, line_height="1.25", **props)


# --- Callout ----------------------------------------------------------------
# Mirrors Radix .rt-CalloutRoot.

_CALLOUT_BASE = "box-border grid items-start justify-start text-left text-[var(--accent-a11)]"
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
