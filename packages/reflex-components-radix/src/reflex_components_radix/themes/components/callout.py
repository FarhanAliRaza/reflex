"""Callout — short attention-grabbing message rendered as Tailwind-styled <div>.

Public API matches the original ``@radix-ui/themes`` Callout. The Root
emits a flex container; Icon is a wrapper for the leading svg; Text is
the inline copy. No dependency on ``@radix-ui/themes`` precompiled CSS.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, ComponentNamespace, field
from reflex_base.vars.base import Var
from reflex_components_core.base.fragment import fragment
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import callout_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor

CalloutVariant = Literal["soft", "surface", "outline"]


class CalloutRoot(elements.Div):
    """Container for Callout's icon and text."""

    tag = "div"

    as_child: Var[bool] = field(doc="Render as child element merging props")
    size: Var[Responsive[Literal["1", "2", "3"]]] = field(doc='Size "1" - "3"')
    variant: Var[CalloutVariant] = field(doc='Variant: soft|surface|outline')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a Callout root.

        Args:
            *children: CalloutIcon + CalloutText children.
            **props: Variant/size/colour props.

        Returns:
            The CalloutRoot component.
        """
        variant = props.pop("variant", None)
        size = props.pop("size", None)
        existing = props.pop("class_name", "")
        selections: dict[str, str] = {}
        if isinstance(variant, str):
            selections["variant"] = variant
        elif variant is not None:
            props["variant"] = variant
        if isinstance(size, str):
            selections["size"] = size
        elif size is not None:
            props["size"] = size
        props["class_name"] = cn(callout_classes(**selections), existing)
        return super().create(*children, **props)


class CalloutIcon(elements.Div):
    """Wrapper for the icon paired with a Callout."""

    tag = "div"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a Callout icon wrapper.

        Args:
            *children: The icon component.
            **props: Standard div props.

        Returns:
            The CalloutIcon component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("flex items-center", existing)
        return super().create(*children, **props)


class CalloutText(elements.P):
    """Inline copy paired with a Callout."""

    tag = "p"

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a Callout text node.

        Args:
            *children: Text content.
            **props: Standard p props.

        Returns:
            The CalloutText component.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn("flex-1", existing)
        return super().create(*children, **props)


class Callout(CalloutRoot):
    """A short message to attract user's attention."""

    text: Var[str] = field(doc="The text of the callout.")
    icon: Var[str] = field(doc="The icon of the callout.")

    @classmethod
    def create(cls, text: str | Var[str], **props: Any) -> Component:
        """Create a callout with text and an optional icon.

        Args:
            text: The callout text.
            **props: Component properties (icon, variant, size, etc.).

        Returns:
            The callout component.
        """
        from reflex_components_lucide.icon import Icon

        return CalloutRoot.create(
            (
                CalloutIcon.create(Icon.create(tag=props.pop("icon")))
                if "icon" in props
                else fragment()
            ),
            CalloutText.create(text),
            **props,
        )


class CalloutNamespace(ComponentNamespace):
    """Callout components namespace."""

    root = staticmethod(CalloutRoot.create)
    icon = staticmethod(CalloutIcon.create)
    text = staticmethod(CalloutText.create)
    __call__ = staticmethod(Callout.create)


callout = CalloutNamespace()
