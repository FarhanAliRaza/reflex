"""DataList — semantic ``<dl>`` family with Tailwind utility classes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


class DataListRoot(elements.Dl):
    """Root element for a DataList."""

    tag = "dl"

    orientation: Var[Responsive[Literal["horizontal", "vertical"]]] = field(
        doc='Orientation: horizontal|vertical'
    )
    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size: "1"|"2"|"3"')
    trim: Var[Responsive[Literal["normal", "start", "end", "both"]]] = field(doc="Trim")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a DataList root.

        Args:
            *children: Item children.
            **props: orientation/size + standard dl props.

        Returns:
            The dl component.
        """
        orientation = props.pop("orientation", "vertical")
        existing = props.pop("class_name", "")
        if isinstance(orientation, str):
            cls_str = (
                "grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2"
                if orientation == "horizontal"
                else "flex flex-col gap-2"
            )
        else:
            cls_str = "flex flex-col gap-2"
            props["orientation"] = orientation
        props["class_name"] = cn(cls_str, existing)
        return super().create(*children, **props)


class DataListItem(elements.Div):
    """An item in the DataList."""

    tag = "div"

    align: Var[Responsive[Literal["start", "center", "end", "baseline", "stretch"]]] = field(
        doc="Item alignment"
    )

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a DataList item wrapper.

        Args:
            *children: Label and value.
            **props: Standard div props.

        Returns:
            The item component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "contents text-sm",
            existing,
        )
        return super().create(*children, **props)


class DataListLabel(elements.Dt):
    """A label in the DataList."""

    tag = "dt"

    width: Var[Responsive[str]] = field(doc="Width")
    min_width: Var[Responsive[str]] = field(doc="Min width")
    max_width: Var[Responsive[str]] = field(doc="Max width")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a DataList label.

        Args:
            *children: Label content.
            **props: Standard dt props.

        Returns:
            The dt component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "text-[var(--gray-11)] font-medium",
            existing,
        )
        return super().create(*children, **props)


class DataListValue(elements.Dd):
    """A value in the DataList."""

    tag = "dd"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a DataList value.

        Args:
            *children: Value content.
            **props: Standard dd props.

        Returns:
            The dd component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("text-[var(--gray-12)]", existing)
        return super().create(*children, **props)


class DataList(SimpleNamespace):
    """DataList components namespace."""

    root = staticmethod(DataListRoot.create)
    item = staticmethod(DataListItem.create)
    label = staticmethod(DataListLabel.create)
    value = staticmethod(DataListValue.create)


data_list = DataList()
