"""CheckboxGroup — group of checkboxes sharing a name + variant."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import checkbox_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor


class CheckboxGroupRoot(elements.Div):
    """Root element for a CheckboxGroup."""

    tag = "div"

    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc="Checkbox size")
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast")
    default_value: Var[Sequence[str]] = field(doc="Pre-checked values")
    name: Var[str] = field(doc="Group name")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a CheckboxGroup root.

        Args:
            *children: CheckboxGroupItem children.
            **props: variant/size/colour props.

        Returns:
            The group component.
        """
        existing = props.pop("class_name", "")
        props.setdefault("role", "group")
        props["class_name"] = cn("flex flex-col gap-2", existing)
        return super().create(*children, **props)


class CheckboxGroupItem(elements.Input):
    """An item in a CheckboxGroup."""

    tag = "input"

    value: Var[str] = field(doc="Item value")
    disabled: Var[bool] = field(doc="Disable")

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a CheckboxGroup item.

        Args:
            *children: Ignored.
            **props: ``value`` plus standard input props.

        Returns:
            The checkbox component.
        """
        existing = props.pop("class_name", "")
        props["type"] = "checkbox"
        props["class_name"] = cn(
            checkbox_classes(), "appearance-none", existing,
        )
        return super().create(**props)


class CheckboxGroup(SimpleNamespace):
    """CheckboxGroup components namespace."""

    root = staticmethod(CheckboxGroupRoot.create)
    item = staticmethod(CheckboxGroupItem.create)


checkbox_group = CheckboxGroup()
