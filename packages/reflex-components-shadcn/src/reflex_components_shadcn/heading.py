"""shadcn-style typography for headings.

Each helper compiles to the matching ``<hN>`` element with Tailwind
utility classes that mirror shadcn/ui's typography rules. Drop-in for
``rx.heading(...)`` on content pages.
"""

from __future__ import annotations

from reflex_base.components.component import Component
from reflex_components_core.el.elements.sectioning import H1, H2, H3, H4, H5, H6

from ._variants import cn

# Class strings tracked from shadcn's Typography reference implementation
# (https://ui.shadcn.com/docs/components/typography). Reflex resolves them
# at compile time so the JSX output is a single class string.
_H1 = "scroll-m-20 text-4xl font-extrabold tracking-tight lg:text-5xl"
_H2 = "scroll-m-20 border-b pb-2 text-3xl font-semibold tracking-tight"
_H3 = "scroll-m-20 text-2xl font-semibold tracking-tight"
_H4 = "scroll-m-20 text-xl font-semibold tracking-tight"
_H5 = "scroll-m-20 text-lg font-semibold tracking-tight"
_H6 = "scroll-m-20 text-base font-semibold tracking-tight"


def _heading_factory(html_class: type, base: str):
    class _Wrapped(html_class):
        @classmethod
        def create(cls, *children, **props) -> Component:
            existing = props.pop("class_name", "")
            props["class_name"] = cn(base, existing)
            return super().create(*children, **props)

    return _Wrapped.create


h1 = _heading_factory(H1, _H1)
h2 = _heading_factory(H2, _H2)
h3 = _heading_factory(H3, _H3)
h4 = _heading_factory(H4, _H4)
h5 = _heading_factory(H5, _H5)
h6 = _heading_factory(H6, _H6)
