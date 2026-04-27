"""Avatar — image-or-fallback element styled with Tailwind utilities."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.cond import cond
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import avatar_classes
from reflex_components_radix._variants import cn, radius_class
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralRadius

LiteralSize = Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"]


class Avatar(elements.Span):
    """An image element with a fallback for representing the user."""

    tag = "span"

    variant: Var[Literal["solid", "soft"]] = field(doc="Variant: solid|soft")
    size: Var[Responsive[LiteralSize]] = field(doc='Size: "1" - "9"')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    high_contrast: Var[bool] = field(doc="Higher contrast variant")
    radius: Var[LiteralRadius] = field(doc="Override theme radius")

    src: Var[str] = field(doc="Image src")
    fallback: Var[str] = field(doc="Fallback text shown when src is missing or fails")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create an avatar.

        Args:
            *children: Optional override content (else fallback shown).
            **props: variant/size/colour + ``src`` / ``fallback`` props.

        Returns:
            The avatar component.
        """
        variant = props.pop("variant", None)
        size = props.pop("size", None)
        radius = props.pop("radius", None)
        src = props.pop("src", None)
        fallback = props.pop("fallback", None)
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
        # ``radius`` overrides the theme's default rounding (e.g.
        # ``radius="full"`` -> circular avatar). Append it after the base
        # class so the override wins over ``rounded-(--radius-3)``.
        radius_cls = radius_class(radius)
        props["class_name"] = cn(avatar_classes(**selections), radius_cls, existing)

        inner: list[Any] = list(children)
        if not inner:
            if src is not None:
                inner.append(
                    cond(
                        src,
                        elements.Img.create(
                            src=src,
                            alt="",
                            class_name="size-full object-cover",
                        ),
                        fallback if fallback is not None else "",
                    )
                )
            elif fallback is not None:
                inner.append(fallback)
        return super().create(*inner, **props)


avatar = Avatar.create
