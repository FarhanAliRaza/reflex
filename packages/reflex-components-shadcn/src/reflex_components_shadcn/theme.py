"""Tailwind theme preflight for the shadcn-style components.

Returns the minimal CSS string the user inlines into their app stylesheet.
Defines the CSS variables every shadcn component references
(``--background``, ``--foreground``, ``--primary``, ``--border``, …) and
the ``.dark`` overrides. Total uncompressed size: ~3 KB.

Usage with ``TailwindV4Plugin``:

>>> from reflex_components_shadcn import shadcn_global_css
>>> custom_css_path = "assets/shadcn-theme.css"
>>> # Write shadcn_global_css() to that file at build time, then
>>> # include it in stylesheets=[...] on rx.App.

The variables match shadcn/ui's reference theme defaults so any
documentation example or third-party shadcn block drops in unchanged.
"""

from __future__ import annotations

from functools import cache


@cache
def shadcn_global_css() -> str:
    """Return the shadcn theme preflight CSS.

    Returns:
        The CSS string. Contains:
        - ``@layer base`` token definitions for the light theme.
        - ``.dark`` overrides for the dark theme.
        - A short reset for ``body`` / ``html`` to apply the tokens.

        Tailwind utilities like ``bg-primary`` / ``text-foreground``
        consume these variables via the Tailwind config exposed by
        :func:`shadcn_tailwind_theme`.
    """
    return r""":root {
  --background: 0 0% 100%;
  --foreground: 240 10% 3.9%;
  --card: 0 0% 100%;
  --card-foreground: 240 10% 3.9%;
  --popover: 0 0% 100%;
  --popover-foreground: 240 10% 3.9%;
  --primary: 240 5.9% 10%;
  --primary-foreground: 0 0% 98%;
  --secondary: 240 4.8% 95.9%;
  --secondary-foreground: 240 5.9% 10%;
  --muted: 240 4.8% 95.9%;
  --muted-foreground: 240 3.8% 46.1%;
  --accent: 240 4.8% 95.9%;
  --accent-foreground: 240 5.9% 10%;
  --destructive: 0 84.2% 60.2%;
  --destructive-foreground: 0 0% 98%;
  --border: 240 5.9% 90%;
  --input: 240 5.9% 90%;
  --ring: 240 5.9% 10%;
  --radius: 0.5rem;
}

.dark {
  --background: 240 10% 3.9%;
  --foreground: 0 0% 98%;
  --card: 240 10% 3.9%;
  --card-foreground: 0 0% 98%;
  --popover: 240 10% 3.9%;
  --popover-foreground: 0 0% 98%;
  --primary: 0 0% 98%;
  --primary-foreground: 240 5.9% 10%;
  --secondary: 240 3.7% 15.9%;
  --secondary-foreground: 0 0% 98%;
  --muted: 240 3.7% 15.9%;
  --muted-foreground: 240 5% 64.9%;
  --accent: 240 3.7% 15.9%;
  --accent-foreground: 0 0% 98%;
  --destructive: 0 62.8% 30.6%;
  --destructive-foreground: 0 0% 98%;
  --border: 240 3.7% 15.9%;
  --input: 240 3.7% 15.9%;
  --ring: 240 4.9% 83.9%;
}

* {
  border-color: hsl(var(--border));
}

body {
  background-color: hsl(var(--background));
  color: hsl(var(--foreground));
  font-feature-settings: "rlig" 1, "calt" 1;
}
"""


@cache
def shadcn_tailwind_theme() -> dict:
    """Return the Tailwind theme extension that maps utilities to the variables.

    Drop-in for ``rx.plugins.TailwindV4Plugin(theme=...)`` or copy into the
    user's existing ``tailwind.config`` ``extend.colors`` block. Adding
    these mappings is what makes ``bg-primary``, ``text-foreground``,
    etc. resolve against the CSS variables defined by
    :func:`shadcn_global_css`.

    Returns:
        A Tailwind ``theme.extend`` dict with the shadcn color/border-radius
        tokens.
    """
    return {
        "extend": {
            "colors": {
                "border": "hsl(var(--border))",
                "input": "hsl(var(--input))",
                "ring": "hsl(var(--ring))",
                "background": "hsl(var(--background))",
                "foreground": "hsl(var(--foreground))",
                "primary": {
                    "DEFAULT": "hsl(var(--primary))",
                    "foreground": "hsl(var(--primary-foreground))",
                },
                "secondary": {
                    "DEFAULT": "hsl(var(--secondary))",
                    "foreground": "hsl(var(--secondary-foreground))",
                },
                "destructive": {
                    "DEFAULT": "hsl(var(--destructive))",
                    "foreground": "hsl(var(--destructive-foreground))",
                },
                "muted": {
                    "DEFAULT": "hsl(var(--muted))",
                    "foreground": "hsl(var(--muted-foreground))",
                },
                "accent": {
                    "DEFAULT": "hsl(var(--accent))",
                    "foreground": "hsl(var(--accent-foreground))",
                },
                "popover": {
                    "DEFAULT": "hsl(var(--popover))",
                    "foreground": "hsl(var(--popover-foreground))",
                },
                "card": {
                    "DEFAULT": "hsl(var(--card))",
                    "foreground": "hsl(var(--card-foreground))",
                },
            },
            "borderRadius": {
                "lg": "var(--radius)",
                "md": "calc(var(--radius) - 2px)",
                "sm": "calc(var(--radius) - 4px)",
            },
        },
    }
