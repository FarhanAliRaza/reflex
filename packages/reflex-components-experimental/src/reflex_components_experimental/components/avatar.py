"""Radix-parity avatar (mirrors ``.rt-AvatarRoot`` + ``.rt-AvatarFallback``)."""

import reflex as rx
from reflex_components_experimental.utils import merge_class_name

_AVATAR_BASE = (
    "inline-flex items-center justify-center align-middle select-none shrink-0 "
    "relative overflow-hidden uppercase font-medium leading-none "
    "font-[family-name:var(--default-font-family)]"
)
# size -> (avatar-size, radius idx, letter-spacing idx, one-letter font-size idx)
# Sizes 6-9 use literal px like .rt-AvatarRoot (beyond the --space scale).
_AVATAR_SIZES = {
    "1": ("var(--space-5)", "2", "1", "2"),
    "2": ("var(--space-6)", "2", "2", "3"),
    "3": ("var(--space-7)", "3", "3", "4"),
    "4": ("var(--space-8)", "3", "4", "5"),
    "5": ("var(--space-9)", "4", "6", "6"),
    "6": ("80px", "5", "7", "7"),
    "7": ("96px", "5", "7", "7"),
    "8": ("128px", "6", "8", "8"),
    "9": ("160px", "6", "9", "9"),
}
_AVATAR_VARIANTS = {
    "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)]",
}


def avatar(*children, size: str = "3", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful avatar with a styled fallback tile.

    Args:
        *children: Fallback content (e.g. initials).
        size: "1"-"9".
        variant: solid/soft (the fallback background, like Radix).
        **props: Extra props; ``class_name`` overrides win via cn.

    Returns:
        The avatar element.
    """
    asz, rad, ls, fs = _AVATAR_SIZES[size]
    cls = (
        f"{_AVATAR_BASE} w-[{asz}] h-[{asz}] "
        f"text-[length:var(--font-size-{fs})] tracking-[var(--letter-spacing-{ls})] "
        f"rounded-[max(var(--radius-{rad}),var(--radius-full))] "
        f"{_AVATAR_VARIANTS[variant]}"
    )
    merge_class_name(cls, props)
    return rx.el.span(*children, **props)
