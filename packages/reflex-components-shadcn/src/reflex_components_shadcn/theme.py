"""Tailwind theme preflight for the shadcn-style components.

The shadcn semantic tokens (``--primary``, ``--secondary``, ``--muted``,
``--accent``, ``--destructive``, ``--background``, ``--foreground``,
``--border``, ``--input``, ``--ring``) are aliased to the same
``--accent-*`` / ``--gray-*`` scale Radix Themes already emits on
``[data-accent-color]`` / ``[data-gray-color]``. That means a user's
``rx.theme(accent_color="violet")`` automatically tints every shadcn
button, card, etc., with **no extra CSS** beyond the small alias block
defined here.

Total uncompressed size: ~2 KB. Variables are stored as raw colors
(e.g. ``var(--accent-9)``) rather than HSL channel triplets so the
``hsl(var(--primary))`` indirection used by stock shadcn templates is
replaced with direct ``background-color: var(--primary)``. The Tailwind
theme exported by :func:`shadcn_tailwind_theme` does this mapping.

Usage::

    from reflex_components_shadcn import shadcn_global_css
    custom_css_path = "assets/shadcn-theme.css"
    # Write shadcn_global_css() to that file at build time, then
    # include it in stylesheets=[...] on rx.App.
"""

from __future__ import annotations

from functools import cache


@cache
def shadcn_global_css() -> str:
    """Return the shadcn semantic-token alias CSS.

    Maps the shadcn semantic tokens (``--primary``, ``--secondary``,
    etc.) onto the Radix accent / gray scales so a single
    ``rx.theme(accent_color=...)`` call drives both component families.

    Returns:
        CSS string emitting the alias variables on ``:root``. Pair with
        the Tailwind theme returned by :func:`shadcn_tailwind_theme`.
    """
    return r""":root {
  --primary: var(--accent-9);
  --primary-foreground: var(--accent-contrast);
  --primary-hover: var(--accent-10);

  --secondary: var(--accent-3);
  --secondary-foreground: var(--accent-11);
  --secondary-hover: var(--accent-4);

  --muted: var(--gray-3);
  --muted-foreground: var(--gray-11);

  --accent: var(--accent-3);
  --accent-foreground: var(--accent-11);
  --accent-hover: var(--accent-4);

  --destructive: var(--red-9);
  --destructive-foreground: white;
  --destructive-hover: var(--red-10);

  --background: var(--color-background);
  --foreground: var(--gray-12);

  --card: var(--color-panel);
  --card-foreground: var(--gray-12);

  --popover: var(--color-panel-solid);
  --popover-foreground: var(--gray-12);

  --border: var(--gray-a6);
  --input: var(--gray-a6);
  --ring: var(--accent-8);

  --radius: var(--radius-3);
  --radius-sm: var(--radius-2);
  --radius-md: var(--radius-3);
  --radius-lg: var(--radius-4);
}
"""


@cache
def shadcn_tailwind_theme() -> dict:
    """Return the Tailwind ``theme.extend`` mapping utilities to the alias variables.

    Drop into ``rx.plugins.TailwindV4Plugin(theme=...)`` (or copy into
    the user's existing tailwind config). The mappings here make
    ``bg-primary``, ``text-foreground``, ``border-input`` etc. resolve
    against the variables defined in :func:`shadcn_global_css`, which
    in turn alias to Radix's accent / gray scales.

    Returns:
        Tailwind ``theme.extend`` dict.
    """
    return {
        "extend": {
            "colors": {
                "border": "var(--border)",
                "input": "var(--input)",
                "ring": "var(--ring)",
                "background": "var(--background)",
                "foreground": "var(--foreground)",
                "primary": {
                    "DEFAULT": "var(--primary)",
                    "foreground": "var(--primary-foreground)",
                    "hover": "var(--primary-hover)",
                },
                "secondary": {
                    "DEFAULT": "var(--secondary)",
                    "foreground": "var(--secondary-foreground)",
                    "hover": "var(--secondary-hover)",
                },
                "destructive": {
                    "DEFAULT": "var(--destructive)",
                    "foreground": "var(--destructive-foreground)",
                    "hover": "var(--destructive-hover)",
                },
                "muted": {
                    "DEFAULT": "var(--muted)",
                    "foreground": "var(--muted-foreground)",
                },
                "accent": {
                    "DEFAULT": "var(--accent)",
                    "foreground": "var(--accent-foreground)",
                    "hover": "var(--accent-hover)",
                },
                "popover": {
                    "DEFAULT": "var(--popover)",
                    "foreground": "var(--popover-foreground)",
                },
                "card": {
                    "DEFAULT": "var(--card)",
                    "foreground": "var(--card-foreground)",
                },
            },
            "borderRadius": {
                "lg": "var(--radius-lg)",
                "md": "var(--radius-md)",
                "sm": "var(--radius-sm)",
            },
        },
    }
