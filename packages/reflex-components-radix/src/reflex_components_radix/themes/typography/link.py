"""Link — semantic anchor with React Router / Astro target awareness.

Public API matches the original Radix Themes Link plus the existing
``is_external`` / target-aware routing logic. Tailwind utilities replace
the ``@radix-ui/themes`` styling.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, MemoizationLeaf, field
from reflex_base.utils.imports import ImportDict, ImportVar
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.cond import cond
from reflex_components_core.core.markdown_component_map import MarkdownComponentMap
from reflex_components_core.el.elements.inline import A
from reflex_components_core.react_router.dom import ReactRouterLink

from reflex_components_radix._radix_classes import link_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

from .base import LiteralTextSize, LiteralTextTrim, LiteralTextWeight

LiteralLinkUnderline = Literal["auto", "hover", "always", "none"]


_KNOWN_REACT_ROUTER_LINK_PROPS = frozenset(ReactRouterLink.get_props())


class Link(A, MemoizationLeaf, MarkdownComponentMap):
    """A semantic element for navigation between pages."""

    tag = "a"

    as_child: Var[bool] = field(doc="Render as child")
    size: Var[Responsive[LiteralTextSize]] = field(doc='Text size: "1" - "9"')
    weight: Var[Responsive[LiteralTextWeight]] = field(
        doc="Thickness: light|regular|medium|bold"
    )
    trim: Var[Responsive[LiteralTextTrim]] = field(doc="Trim: normal|start|end|both")
    underline: Var[LiteralLinkUnderline] = field(
        doc="Underline: auto|hover|always|none"
    )
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")
    is_external: Var[bool] = field(doc="If True, opens in a new tab")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    def add_imports(self) -> ImportDict:
        """Add imports for the Link component.

        Returns:
            The import dict. On the Astro target the Link component
            compiles to a plain ``<a>`` and never imports React Router.
        """
        from reflex_base.config import get_config

        if get_config().frontend_target == "astro":
            return {}
        return {
            "react-router": [ImportVar(tag="Link", alias="ReactRouterLink")],
        }

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a Link component.

        Args:
            *children: The children of the component.
            **props: The props of the component.

        Returns:
            The link component.

        Raises:
            ValueError: If a non-empty href is provided without children.
        """
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        for key in ("underline", "size", "weight"):
            value = props.pop(key, None)
            if isinstance(value, str):
                selections[key] = value
            elif value is not None:
                props[key] = value
        props["class_name"] = cn(link_classes(**selections), existing)

        href = props.get("href")
        is_external = props.pop("is_external", None)
        if is_external is not None:
            props["target"] = cond(is_external, "_blank", "")

        if href is not None:
            if not len(children):
                msg = "Link without a child will not display"
                raise ValueError(msg)

            if "as_child" not in props:
                from reflex_base.config import get_config

                if (config := get_config()).frontend_target == "astro":
                    for unsupported in _KNOWN_REACT_ROUTER_LINK_PROPS - {
                        "href",
                        "rel",
                        "target",
                    }:
                        props.pop(unsupported, None)
                    if isinstance(href_value := props.get("href"), str):
                        props["href"] = config.resolve_internal_link_href(href_value)
                    return super().create(*children, **props)

                react_router_link_props: dict[str, Any] = {}
                for prop in props.copy():
                    if prop in _KNOWN_REACT_ROUTER_LINK_PROPS:
                        react_router_link_props[prop] = props.pop(prop)

                react_router_link_props["to"] = react_router_link_props.pop(
                    "href", href
                )

                return super().create(
                    ReactRouterLink.create(*children, **react_router_link_props),
                    as_child=True,
                    **props,
                )
        else:
            props["href"] = "#"

        return super().create(*children, **props)


link = Link.create
