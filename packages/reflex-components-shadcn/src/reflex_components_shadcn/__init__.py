"""shadcn-style Reflex components.

A Tailwind-utility-driven alternative to ``reflex-components-radix``.
Each component compiles to plain HTML elements (or, where behavior is
required, headless ``@radix-ui/react-*`` primitives) with class strings
the Tailwind JIT picks up. There is no monolithic third-party
stylesheet — the only CSS the page ships is the Tailwind utilities
actually used plus a small theme-token preflight (~3 KB).

Use the helpers as drop-in replacements for the corresponding
``rx.*`` factories:

>>> from reflex_components_shadcn import button, card, h1, paragraph
>>> page = card(h1("Hello"), paragraph("World"), button("Click"))

Or opt the whole app in via ``rx.Config(component_library="shadcn")``;
the rx namespace will resolve ``rx.button`` etc. to the shadcn flavor
on the Astro frontend target.
"""

from .badge import badge
from .button import ShadcnButton, button
from .card import (
    card,
    card_content,
    card_description,
    card_footer,
    card_header,
    card_title,
)
from .code import code, code_block
from .heading import h1, h2, h3, h4, h5, h6
from .layout import container, hstack, section, separator, vstack
from .link import link
from .text import paragraph, text
from .theme import shadcn_global_css

__all__ = [
    "ShadcnButton",
    "badge",
    "button",
    "card",
    "card_content",
    "card_description",
    "card_footer",
    "card_header",
    "card_title",
    "code",
    "code_block",
    "container",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hstack",
    "link",
    "paragraph",
    "section",
    "separator",
    "shadcn_global_css",
    "text",
    "vstack",
]
