"""Skeleton — Tailwind-styled placeholder block."""

from __future__ import annotations

from typing import Any

from reflex_base.components.component import Component, field
from reflex_base.constants.compiler import MemoizationMode
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import skeleton_classes
from reflex_components_radix._variants import cn


class Skeleton(elements.Div):
    """Skeleton placeholder shown while content is loading."""

    tag = "div"

    loading: Var[bool] = field(doc="If True, shows the skeleton (default behaviour).")
    width: Var[Responsive[str]] = field(doc="Skeleton width")
    min_width: Var[Responsive[str]] = field(doc="Skeleton min width")
    max_width: Var[Responsive[str]] = field(doc="Skeleton max width")
    height: Var[Responsive[str]] = field(doc="Skeleton height")
    min_height: Var[Responsive[str]] = field(doc="Skeleton min height")
    max_height: Var[Responsive[str]] = field(doc="Skeleton max height")

    _memoization_mode = MemoizationMode(recursive=False)

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a skeleton placeholder.

        Args:
            *children: Optional children to hide while skeleton renders.
            **props: Standard div props.

        Returns:
            The skeleton component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(skeleton_classes(), existing)
        return super().create(*children, **props)


skeleton = Skeleton.create
