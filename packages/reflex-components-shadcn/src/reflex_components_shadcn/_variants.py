"""Compile-time variant helper modeled after class-variance-authority.

shadcn/ui resolves a component's ``className`` string from a base set of
utilities plus per-prop variant + size selectors. We do the same at Python
compile time so the JSX output is a single concatenated string of Tailwind
classes — Tailwind's JIT engine then emits only the utilities actually used
across the project.

Example::

    button_classes = variants(
        base="inline-flex items-center justify-center rounded-md text-sm font-medium",
        variant={
            "default": "bg-primary text-primary-foreground hover:bg-primary/90",
            "outline": "border border-input bg-background hover:bg-accent",
        },
        size={
            "default": "h-9 px-4 py-2",
            "sm": "h-8 rounded-md px-3 text-xs",
        },
        defaults={"variant": "default", "size": "default"},
    )
    button_classes(variant="outline", size="sm")
"""

from __future__ import annotations

from collections.abc import Callable, Mapping


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
            ``{"variant": "default", "size": "default"}``).
        **variant_groups: Each kwarg is a variant group name mapped to a
            ``{key: classes}`` dictionary. The keys are the values the
            caller passes (e.g. ``variant="outline"``); the values are
            the Tailwind utilities applied for that selection.

    Returns:
        A function ``(**selections) -> str`` that returns the merged
        class-name string. Selections that aren't recognised raise
        ``KeyError`` — same shape as ``cva``.
    """
    defaults = dict(defaults or {})

    def resolve(**selections: str) -> str:
        parts = [base]
        for group_name, group_map in variant_groups.items():
            chosen = selections.get(group_name, defaults.get(group_name))
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


def cn(*parts: str | None) -> str:
    """Concatenate class-name strings, dropping ``None`` and empties.

    Equivalent to shadcn's ``cn(...)`` helper minus the ``tailwind-merge``
    step. Reflex resolves variants at Python compile time, so duplicate
    utilities are rare; users who pass conflicting props can override via
    arbitrary Tailwind class strings.

    Args:
        *parts: Class-name fragments. ``None`` and empty strings are
            skipped.

    Returns:
        Single space-separated class-name string.
    """
    return " ".join(p.strip() for p in parts if p)
