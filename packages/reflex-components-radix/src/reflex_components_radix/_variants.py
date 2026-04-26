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
        if p is None or p == "" or p == []:
            continue
        if isinstance(p, (list, tuple)):
            for inner in p:
                if inner is None or inner == "":
                    continue
                flat.append(inner)
        else:
            flat.append(p)
    if all(isinstance(p, str) for p in flat):
        return " ".join(p.strip() for p in flat if p.strip())  # type: ignore[union-attr]
    return flat
