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
