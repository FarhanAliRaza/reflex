"""Radix-parity inline code (mirrors ``.rt-Code``, default soft variant)."""

import reflex as rx
from reflex_components_experimental.utils import cn

_CODE_BASE = (
    "font-[family-name:var(--code-font-family)] not-italic [font-weight:inherit] "
    "box-border h-fit rounded-[calc((0.5px+0.2em)*var(--radius-factor))] "
    "pt-[var(--code-padding-top)] pb-[var(--code-padding-bottom)] "
    "pl-[var(--code-padding-left)] pr-[var(--code-padding-right)]"
)
_CODE_VARIANTS = {
    "soft": "bg-[var(--accent-a3)] text-[var(--accent-a11)]",
    "solid": "bg-[var(--accent-a9)] text-[var(--accent-contrast)]",
    "outline": "shadow-[inset_0_0_0_max(1px,0.033em)_var(--accent-a8)] text-[var(--accent-a11)]",
}


def code(*children, size: str = "2", variant: str = "soft", **props) -> rx.Component:
    """A Radix-faithful inline code element.

    Args:
        *children: Content.
        size: "1"-"9".
        variant: soft/solid/outline.
        **props: Extra props.

    Returns:
        The code element.
    """
    cls = (
        f"{_CODE_BASE} {_CODE_VARIANTS[variant]} "
        f"text-[length:calc(var(--font-size-{size})*var(--code-font-size-adjust)*0.95)] "
        f"leading-[var(--line-height-{size})] "
        f"tracking-[calc(var(--code-letter-spacing)+var(--letter-spacing-{size}))]"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.code(*children, **props)
