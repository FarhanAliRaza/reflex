"""shadcn-style card components.

Cards compile to nested ``<div>`` elements with Tailwind utility classes.
Drop-in replacement for ``rx.card(...)`` on the Astro target's content
pages — no Radix Themes CSS shipped.
"""

from __future__ import annotations

from reflex_base.components.component import Component
from reflex_components_core.el.elements.typography import Div

from ._variants import cn

_CARD_BASE = "rounded-xl border bg-card text-card-foreground shadow"
_CARD_HEADER_BASE = "flex flex-col space-y-1.5 p-6"
_CARD_TITLE_BASE = "font-semibold leading-none tracking-tight"
_CARD_DESCRIPTION_BASE = "text-sm text-muted-foreground"
_CARD_CONTENT_BASE = "p-6 pt-0"
_CARD_FOOTER_BASE = "flex items-center p-6 pt-0"


def _div_with_classes(base: str):
    """Return a ``Div``-extending class that prepends ``base`` to ``class_name``."""

    class _Wrapped(Div):
        @classmethod
        def create(cls, *children, **props) -> Component:
            existing = props.pop("class_name", "")
            props["class_name"] = cn(base, existing)
            return super().create(*children, **props)

    return _Wrapped


_Card = _div_with_classes(_CARD_BASE)
_CardHeader = _div_with_classes(_CARD_HEADER_BASE)
_CardContent = _div_with_classes(_CARD_CONTENT_BASE)
_CardFooter = _div_with_classes(_CARD_FOOTER_BASE)
_CardTitle = _div_with_classes(_CARD_TITLE_BASE)
_CardDescription = _div_with_classes(_CARD_DESCRIPTION_BASE)


card = _Card.create
card_header = _CardHeader.create
card_title = _CardTitle.create
card_description = _CardDescription.create
card_content = _CardContent.create
card_footer = _CardFooter.create
