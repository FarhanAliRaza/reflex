"""Compile-time variant helper modeled after class-variance-authority.

shadcn/ui resolves a component's ``className`` string from a base set of
utilities plus per-prop variant + size selectors. We do the same at
Python compile time so the JSX output is a single concatenated string
of Tailwind classes — Tailwind's JIT engine then emits only the
utilities actually used across the project.

Example::

    button_classes = variants(
        base="inline-flex items-center justify-center rounded-md text-sm",
        variant={
            "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
            "outline": "border border-[var(--accent-a8)] text-[var(--accent-11)]",
        },
        size={
            "1": "h-6 px-2 text-xs",
            "2": "h-8 px-3 text-sm",
        },
        defaults={"variant": "solid", "size": "2"},
    )
    button_classes(variant="outline", size="1")

The components in this package use these helpers to render directly
to plain HTML elements + Tailwind utilities, replacing the
``@radix-ui/themes`` precompiled CSS.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

# Reflex breakpoint name -> Tailwind v4 prefix. ``base`` / ``initial`` map to
# the unprefixed (mobile-first) class. Reflex's ``xs`` (30em) doesn't have a
# default Tailwind v4 equivalent, so it falls through to ``sm`` to keep the
# class string valid; users who need pixel-perfect ``xs`` should configure a
# custom Tailwind breakpoint.
_BREAKPOINT_PREFIX: dict[str, str] = {
    "base": "",
    "initial": "",
    "xs": "sm:",
    "sm": "sm:",
    "md": "md:",
    "lg": "lg:",
    "xl": "xl:",
    "2xl": "2xl:",
}


def responsive_classes(
    value: Any,
    formatter: Callable[[str], str | None],
) -> str:
    """Translate a ``Responsive[T]`` prop value to a Tailwind class string.

    A ``Responsive`` value is either a plain string (mobile-first single
    value) or a ``{breakpoint: value}`` mapping (Reflex ``Breakpoints``,
    or any plain dict using the same keys). ``formatter`` resolves one
    value at a time to the underlying class — e.g. ``lambda v:
    f"grid-cols-{v}"`` for ``Grid.columns``, or
    ``_DIRECTION.get`` for ``Flex.direction``. Returning ``None`` skips
    the entry, which is how mappings reject unknown values.

    Each non-base breakpoint's class is prefixed with the matching
    Tailwind modifier (``sm:``, ``md:``, ...). Multi-class formatters
    (``"items-center justify-center"``) get the prefix applied to every
    class so ``md:items-center md:justify-center`` survives Tailwind's
    JIT scan.

    Args:
        value: The prop value (str, dict, ``None``, or anything else).
        formatter: Maps a single string value to its Tailwind class.

    Returns:
        A space-separated class string, empty when nothing translates.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return formatter(value) or ""
    if isinstance(value, Mapping):
        parts: list[str] = []
        for breakpoint, raw in value.items():
            if not isinstance(raw, str):
                continue
            cls = formatter(raw)
            if not cls:
                continue
            prefix = _BREAKPOINT_PREFIX.get(breakpoint)
            if prefix is None:
                continue
            if not prefix:
                parts.append(cls)
            else:
                parts.append(" ".join(f"{prefix}{c}" for c in cls.split()))
        return " ".join(parts)
    return ""


# Radix Themes ``radius`` prop -> Tailwind border-radius utility. ``"none"``
# explicitly opts out of any rounding; the other named values defer to the
# theme's ``--radius-N`` CSS variables (so e.g. ``radius="medium"`` uses the
# slot the user picked in ``rx.theme(radius=...)`` via tokens.css). ``"full"``
# is a fully circular corner regardless of theme.
_RADIUS: dict[str, str] = {
    "none": "rounded-none",
    "small": "rounded-(--radius-2)",
    "medium": "rounded-(--radius-3)",
    "large": "rounded-(--radius-4)",
    "full": "rounded-full",
}


def radius_class(value: Any) -> str:
    """Translate a Radix Themes ``radius`` prop to a Tailwind class.

    Mirrors the original Radix Themes API: ``radius`` is a per-component
    override of the theme's default radius. Returns ``""`` when the value
    is missing or unrecognised so callers can append the result without
    extra guards.

    Args:
        value: ``"none" | "small" | "medium" | "large" | "full"`` or
            ``None``.

    Returns:
        The matching ``rounded-*`` class, or ``""``.
    """
    return responsive_classes(value, _RADIUS.get)


def variants(
    *,
    base: str,
    defaults: Mapping[str, str] | None = None,
    **variant_groups: Mapping[str, str],
) -> Callable[..., str]:
    """Build a class-name resolver from a base string + named variant groups.

    Args:
        base: Tailwind utilities applied to every instance.
        defaults: The default key per variant group (e.g.
            ``{"variant": "solid", "size": "2"}``).
        **variant_groups: Each kwarg is a variant group name mapped to a
            ``{key: classes}`` dictionary. The keys are the values the
            caller passes; the values are the Tailwind utilities applied
            for that selection.

    Returns:
        A function ``(**selections) -> str`` returning the merged
        class-name string. Selections that aren't recognised raise
        ``KeyError``.
    """
    defaults_dict = dict(defaults or {})

    def resolve(**selections: str | None) -> str:
        parts = [base]
        for group_name, group_map in variant_groups.items():
            chosen = selections.get(group_name, defaults_dict.get(group_name))
            if chosen is None:
                continue
            classes = group_map.get(chosen)
            if classes is None:
                msg = (
                    f"Unknown {group_name}={chosen!r} for variants(). "
                    f"Expected one of {sorted(group_map)}."
                )
                raise KeyError(msg)
            parts.append(classes)
        return " ".join(p for p in parts if p)

    return resolve


def cn(*parts: object) -> str | list[object]:
    """Concatenate class-name parts.

    Strings are merged into a single space-separated string. If any
    part is a Reflex ``Var`` (or any other non-string), the result is
    flattened to a list so Reflex's render layer can stringify each
    item at runtime — preserving user-supplied dynamic ``class_name``
    values (Vars, ``rx.cond``, etc.). Nested lists/tuples are
    flattened so callers can pass through an existing list-shaped
    ``class_name`` without producing a ``list[list[...]]``.

    Args:
        *parts: Class-name fragments.

    Returns:
        A merged class-name string (when every part is a string), or
        a flattened list of parts otherwise.
    """
    flat: list[object] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, str):
            if p == "":
                continue
            flat.append(p)
        elif isinstance(p, list):
            if not p:
                continue
            for inner in p:
                if inner is None or (isinstance(inner, str) and inner == ""):
                    continue
                flat.append(inner)
        elif isinstance(p, tuple):
            for inner in p:
                if inner is None or (isinstance(inner, str) and inner == ""):
                    continue
                flat.append(inner)
        else:
            # Non-string, non-list (e.g. a Var or rx.cond): pass through
            # without truthiness checks — those raise on Vars.
            flat.append(p)
    if all(isinstance(p, str) for p in flat):
        return " ".join(p.strip() for p in flat if p.strip())  # type: ignore[union-attr]
    return flat
