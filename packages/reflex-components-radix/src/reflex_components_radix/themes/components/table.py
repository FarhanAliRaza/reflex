"""Table — semantic ``<table>`` family with Tailwind utility classes."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._variants import cn, variants
from reflex_components_radix.themes.base import CommonPaddingProps


_root_classes = variants(
    base="w-full caption-bottom text-sm text-[var(--gray-12)]",
    defaults={"size": "2", "variant": "surface"},
    size={
        "1": "text-xs",
        "2": "text-sm",
        "3": "text-base",
    },
    variant={
        "surface": "border border-[var(--gray-a4)] rounded-(--radius-3) overflow-hidden",
        "ghost": "",
    },
)


class TableRoot(elements.Table):
    """A semantic table."""

    tag = "table"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Table size')
    variant: Var[Literal["surface", "ghost"]] = field(doc="Variant")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a table root.

        Args:
            *children: Header / body children.
            **props: variant/size + standard table props.

        Returns:
            The table component.
        """
        size = props.pop("size", None)
        variant = props.pop("variant", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        if isinstance(variant, str):
            selections["variant"] = variant
        elif variant is not None:
            props["variant"] = variant
        props["class_name"] = cn(_root_classes(**selections), existing)
        return super().create(*children, **props)


class TableHeader(elements.Thead):
    """Table header."""

    tag = "thead"

    _invalid_children: ClassVar[list[str]] = ["TableBody"]
    _valid_parents: ClassVar[list[str]] = ["TableRoot"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a table header.

        Args:
            *children: Header rows.
            **props: Standard thead props.

        Returns:
            The thead component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "border-b border-[var(--gray-a5)] bg-[var(--gray-a2)]",
            existing,
        )
        return super().create(*children, **props)


class TableRow(elements.Tr):
    """A row of table cells."""

    tag = "tr"

    align: Var[Literal["start", "center", "end", "baseline"]] = field(doc="Vertical align")

    _invalid_children: ClassVar[list[str]] = ["TableBody", "TableHeader", "TableRow"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a table row.

        Args:
            *children: Cells.
            **props: Standard tr props.

        Returns:
            The tr component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "border-b border-[var(--gray-a4)] last:border-0 "
            "hover:bg-[var(--gray-a2)] transition-colors",
            existing,
        )
        return super().create(*children, **props)


class TableColumnHeaderCell(elements.Th):
    """A column header cell."""

    tag = "th"

    justify: Var[Literal["start", "center", "end"]] = field(doc="Horizontal justify")
    min_width: Var[Responsive[str]] = field(doc="Min width")
    max_width: Var[Responsive[str]] = field(doc="Max width")

    _invalid_children: ClassVar[list[str]] = [
        "TableBody", "TableHeader", "TableRow",
        "TableCell", "TableColumnHeaderCell", "TableRowHeaderCell",
    ]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a column header cell.

        Args:
            *children: Header content.
            **props: Standard th props.

        Returns:
            The th component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "h-10 px-3 text-left align-middle font-medium "
            "text-[var(--gray-11)]",
            existing,
        )
        return super().create(*children, **props)


class TableBody(elements.Tbody):
    """The body of the table."""

    tag = "tbody"

    _invalid_children: ClassVar[list[str]] = [
        "TableHeader", "TableRowHeaderCell",
        "TableColumnHeaderCell", "TableCell",
    ]
    _valid_parents: ClassVar[list[str]] = ["TableRoot"]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create the table body.

        Args:
            *children: Body rows.
            **props: Standard tbody props.

        Returns:
            The tbody component.
        """
        return super().create(*children, **props)


class TableCell(elements.Td, CommonPaddingProps):
    """A data cell."""

    tag = "td"

    justify: Var[Literal["start", "center", "end"]] = field(doc="Horizontal justify")
    min_width: Var[Responsive[str]] = field(doc="Min width")
    max_width: Var[Responsive[str]] = field(doc="Max width")

    _invalid_children: ClassVar[list[str]] = [
        "TableBody", "TableHeader",
        "TableRowHeaderCell", "TableColumnHeaderCell", "TableCell",
    ]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a table cell.

        Args:
            *children: Cell content.
            **props: Standard td props.

        Returns:
            The td component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("px-3 py-2 align-middle", existing)
        return super().create(*children, **props)


class TableRowHeaderCell(elements.Th, CommonPaddingProps):
    """A row header cell."""

    tag = "th"

    justify: Var[Literal["start", "center", "end"]] = field(doc="Horizontal justify")
    min_width: Var[Responsive[str]] = field(doc="Min width")
    max_width: Var[Responsive[str]] = field(doc="Max width")

    _invalid_children: ClassVar[list[str]] = [
        "TableBody", "TableHeader", "TableRow",
        "TableCell", "TableColumnHeaderCell", "TableRowHeaderCell",
    ]

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a row header cell.

        Args:
            *children: Cell content.
            **props: Standard th props.

        Returns:
            The th component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(
            "px-3 py-2 align-middle text-left font-medium text-[var(--gray-12)]",
            existing,
        )
        return super().create(*children, **props)


class Table(ComponentNamespace):
    """Table components namespace."""

    root = staticmethod(TableRoot.create)
    header = staticmethod(TableHeader.create)
    body = staticmethod(TableBody.create)
    row = staticmethod(TableRow.create)
    cell = staticmethod(TableCell.create)
    column_header_cell = staticmethod(TableColumnHeaderCell.create)
    row_header_cell = staticmethod(TableRowHeaderCell.create)


table = Table()
