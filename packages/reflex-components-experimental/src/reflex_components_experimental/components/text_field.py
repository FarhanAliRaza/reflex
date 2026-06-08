"""Radix-parity text field (mirrors ``.rt-TextFieldRoot`` box model).

The MEASURED element is Radix's flex Root (not the inner input); a single input
reproduces the Root box. ``text-indent`` insets text without changing measured
padding. ``line-height`` is inherited (1.5).
"""

import reflex as rx
from reflex_components_experimental.utils import cn

_TF_BASE = (
    "box-border flex items-stretch text-start not-italic "
    "font-[family-name:var(--default-font-family)] font-[400] "
    "leading-[1.5] appearance-none border-0 outline-0 m-0 [background-clip:content-box]"
)
_TF_SIZES = {
    "1": (
        "--space-5",
        "max(var(--radius-2),var(--radius-full))",
        "1",
        "calc(var(--space-1)*1.5-var(--tf-bw))",
    ),
    "2": (
        "--space-6",
        "max(var(--radius-2),var(--radius-full))",
        "2",
        "calc(var(--space-2)-var(--tf-bw))",
    ),
    "3": (
        "--space-7",
        "max(var(--radius-3),var(--radius-full))",
        "3",
        "calc(var(--space-3)-var(--tf-bw))",
    ),
}
_TF_VARIANTS = {
    "surface": (
        "1px",
        "bg-[var(--color-surface)]",
        "text-[var(--gray-12)]",
        "shadow-[inset_0_0_0_1px_var(--gray-a7)]",
    ),
    "soft": ("0px", "bg-[var(--accent-a3)]", "text-[var(--accent-12)]", ""),
}


def text_field(
    *children, size: str = "2", variant: str = "surface", **props
) -> rx.Component:
    """A Radix-faithful text field (matches .rt-TextFieldRoot box model).

    Returns:
        The rendered component.
    """
    height, radius, fs, pad = _TF_SIZES[size]
    bw, bg, color, shadow = _TF_VARIANTS[variant]
    cls = (
        f"{_TF_BASE} [--tf-bw:{bw}] h-[var({height})] p-[var(--tf-bw)] rounded-[{radius}] "
        f"text-[length:var(--font-size-{fs})] tracking-[var(--letter-spacing-{fs})] "
        f"[text-indent:{pad}] {bg} {color} {shadow}"
    )
    props["class_name"] = cn(cls, props.pop("class_name", ""))
    return rx.el.input(**props)
