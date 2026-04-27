"""TextArea — native ``<textarea>`` with Tailwind utility classes."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from reflex_base.components.component import Component, field
from reflex_base.vars.base import Var
from reflex_components_core.core.breakpoints import Responsive
from reflex_components_core.core.debounce import DebounceInput
from reflex_components_core.el import elements

from reflex_components_radix._radix_classes import text_area_classes
from reflex_components_radix._variants import cn
from reflex_components_radix.themes.base import LiteralAccentColor, LiteralRadius

LiteralTextAreaSize = Literal["1", "2", "3"]
LiteralTextAreaResize = Literal["none", "vertical", "horizontal", "both"]

_RESIZE = {
    "none": "resize-none",
    "vertical": "resize-y",
    "horizontal": "resize-x",
    "both": "resize",
}


class TextArea(elements.Textarea):
    """A multi-line text input."""

    tag = "textarea"

    size: Var[Responsive[LiteralTextAreaSize]] = field(doc='Size: "1" | "2" | "3"')
    variant: Var[Literal["classic", "surface", "soft"]] = field(doc="Variant")
    resize: Var[Responsive[LiteralTextAreaResize]] = field(doc='Resize: none|vertical|horizontal|both')
    color_scheme: Var[LiteralAccentColor] = field(doc="Override accent color")
    radius: Var[LiteralRadius] = field(doc="Override theme radius")

    auto_complete: Var[bool] = field(doc="Enable autocomplete")
    auto_focus: Var[bool] = field(doc="Autofocus on mount")
    default_value: Var[str] = field(doc="Initial value")
    dirname: Var[str] = field(doc="dirname")
    disabled: Var[bool] = field(doc="Disable")
    form: Var[str] = field(doc="Form id")
    max_length: Var[int] = field(doc="Max chars")
    min_length: Var[int] = field(doc="Min chars")
    name: Var[str] = field(doc="Form name")
    placeholder: Var[str] = field(doc="Placeholder")
    read_only: Var[bool] = field(doc="Read-only")
    required: Var[bool] = field(doc="Required")
    rows: Var[str] = field(doc="Number of visible rows")
    value: Var[str] = field(doc="Controlled value")
    wrap: Var[str] = field(doc="Wrap mode")

    _rename_props: ClassVar[dict[str, str]] = {"colorScheme": "data-accent-color"}

    @classmethod
    def create(cls, *children: Any, **props: Any) -> Component:
        """Create a textarea.

        Args:
            *children: Default text content.
            **props: Standard textarea props plus variant/size/resize.

        Returns:
            The textarea component (debounced if controlled).
        """
        variant = props.pop("variant", None)
        size = props.pop("size", None)
        resize = props.pop("resize", None)
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
        parts = [text_area_classes(**selections)]
        if isinstance(resize, str):
            parts.append(_RESIZE[resize])
        elif resize is not None:
            props["resize"] = resize
        props["class_name"] = cn(" ".join(parts), existing)

        if props.get("value") is not None and props.get("on_change") is not None:
            return DebounceInput.create(super().create(*children, **props))
        return super().create(*children, **props)


text_area = TextArea.create
