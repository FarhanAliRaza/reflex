"""Box — fundamental layout primitive (plain ``<div>``)."""

from __future__ import annotations

from reflex_components_core.el import elements


class Box(elements.Div):
    """A fundamental layout building block, based on the ``<div>`` element."""

    tag = "div"


box = Box.create
