"""shadcn-style link.

Compiles to a plain ``<a href>`` element with shadcn-typography link
classes. No React Router involvement — internal navigation is document-
based on the Astro target. ``frontend_path`` is honored via the existing
``Config.resolve_internal_link_href`` helper.
"""

from __future__ import annotations

from reflex_base.components.component import Component
from reflex_base.config import get_config
from reflex_components_core.el.elements.inline import A

from ._variants import cn

_LINK_BASE = (
    "font-medium text-primary underline underline-offset-4 hover:text-primary/80"
)


class ShadcnLink(A):
    """An ``<a>`` styled with shadcn link defaults."""

    @classmethod
    def create(cls, *children, **props) -> Component:
        """Render an internal/external link.

        Args:
            *children: Link children.
            **props: Standard anchor attributes; ``href`` is rewritten
                through ``Config.resolve_internal_link_href`` so apps
                with a configured ``frontend_path`` get the right
                base prefix.

        Returns:
            The anchor component.
        """
        href = props.get("href")
        if isinstance(href, str):
            resolver = getattr(get_config(), "resolve_internal_link_href", None)
            if callable(resolver):
                props["href"] = resolver(href)
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_LINK_BASE, existing)
        return super().create(*children, **props)


link = ShadcnLink.create
