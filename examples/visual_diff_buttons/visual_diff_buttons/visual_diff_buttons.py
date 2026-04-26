"""Side-by-side comparison: Radix Themes Button vs shadcn Button.

Each row pairs the current ``rx.button`` (Radix Themes, ``@radix-ui/themes``
precompiled CSS) with the new ``shadcn_button`` (Tailwind utilities + Radix
Primitives only) so you can visually verify pixel parity for each variant
and size. The column headers note the exact prop combination so a screenshot
diff tool can crop a single cell and pixel-compare.

Run::

    cd examples/visual_diff_buttons
    uv run reflex run

Then open http://localhost:3000 — the page is the comparison grid. To
capture a screenshot for diffing run ``uv run python capture.py``.
"""

from __future__ import annotations

import reflex as rx
from reflex_components_shadcn import button as shadcn_button

RADIX_VARIANTS: list[str] = ["solid", "soft", "outline", "surface", "ghost", "classic"]
RADIX_SIZES: list[str] = ["1", "2", "3", "4"]

SHADCN_VARIANT_FOR_RADIX: dict[str, str] = {
    "solid": "default",
    "soft": "secondary",
    "outline": "outline",
    "surface": "outline",
    "ghost": "ghost",
    "classic": "default",
}
SHADCN_SIZE_FOR_RADIX: dict[str, str] = {
    "1": "sm",
    "2": "default",
    "3": "lg",
    "4": "xl",
}


def _cell(content, label: str) -> rx.Component:
    return rx.box(
        content,
        rx.text(label, class_name="mt-2 text-[10px] font-mono text-gray-500"),
        class_name="flex flex-col items-center p-4 border border-gray-200 rounded",
    )


def _row_for_size(size: str) -> rx.Component:
    cells: list[rx.Component] = []
    for variant in RADIX_VARIANTS:
        radix = rx.button(
            f"{variant} / {size}",
            variant=variant,  # pyright: ignore[reportArgumentType]
            size=size,  # pyright: ignore[reportArgumentType]
        )
        shadcn = shadcn_button(
            f"{variant} / {size}",
            variant=SHADCN_VARIANT_FOR_RADIX[variant],
            size=SHADCN_SIZE_FOR_RADIX[size],
        )
        cells.append(
            rx.hstack(
                _cell(radix, f"radix {variant} sz={size}"),
                _cell(
                    shadcn,
                    f"shadcn {SHADCN_VARIANT_FOR_RADIX[variant]} "
                    f"sz={SHADCN_SIZE_FOR_RADIX[size]}",
                ),
                gap="2",
                class_name="items-center",
            )
        )
    return rx.box(
        rx.heading(f"size {size}", size="3", class_name="mb-2"),
        rx.flex(*cells, wrap="wrap", gap="3"),
        class_name="mb-8",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("Button visual diff", size="6"),
            rx.text(
                "Left = current rx.button (Radix Themes, ~600 KB CSS). "
                "Right = shadcn rewrite (Tailwind utilities, ~16 KB CSS). "
                "Rows below pair them by closest equivalent variant/size.",
                class_name="mb-4 text-sm text-gray-700",
            ),
            *[_row_for_size(size) for size in RADIX_SIZES],
            class_name="py-8",
            align="start",
        ),
        size="4",
    )


app = rx.App()
app.add_page(index, route="/", title="Button visual diff")
