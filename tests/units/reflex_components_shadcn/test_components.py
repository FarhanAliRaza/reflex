"""Smoke + class-name tests for shadcn-style Reflex components.

Each test verifies the generated ``class_name`` contains the expected
shadcn utilities, that user-supplied class names are appended (not
replaced), and that unrecognized variants raise.
"""

from __future__ import annotations

import pytest
from reflex_components_shadcn import (
    badge,
    button,
    card,
    card_content,
    card_description,
    card_footer,
    card_header,
    card_title,
    code,
    code_block,
    container,
    h1,
    h2,
    h3,
    hstack,
    link,
    paragraph,
    section,
    separator,
    shadcn_global_css,
    text,
    vstack,
)
from reflex_components_shadcn.theme import shadcn_tailwind_theme


def test_button_default_variant_and_size():
    b = button("Click")
    cls = b.class_name
    assert "bg-primary" in cls
    assert "text-primary-foreground" in cls
    assert "h-9 px-4 py-2" in cls


def test_button_outline_variant():
    b = button("Click", variant="outline")
    assert "border-input" in b.class_name
    assert "bg-primary" not in b.class_name


def test_button_size_sm_lg_icon():
    assert "h-8" in button("a", size="sm").class_name
    assert "h-10" in button("a", size="lg").class_name
    assert "h-9 w-9" in button("a", size="icon").class_name


def test_button_appends_user_class_name():
    b = button("Click", class_name="my-extra")
    cls = b.class_name
    assert "my-extra" in cls
    assert "bg-primary" in cls


def test_button_unknown_variant_raises():
    with pytest.raises(KeyError, match="variant='ghosty'"):
        button("Click", variant="ghosty")  # pyright: ignore[reportArgumentType]


def test_h1_h6_classes():
    assert "text-4xl" in h1("x").class_name
    assert "text-3xl" in h2("x").class_name
    assert "text-2xl" in h3("x").class_name


def test_paragraph_classes():
    cls = paragraph("hello").class_name
    assert "leading-7" in cls
    assert "text-base" in cls


def test_paragraph_muted_tone():
    cls = paragraph("hello", tone="muted").class_name
    assert "text-muted-foreground" in cls


def test_text_inline_span_default():
    cls = text("inline").class_name
    assert "text-base" in cls
    assert "text-foreground" in cls


def test_card_set():
    assert "rounded-xl" in card().class_name
    assert "p-6" in card_header().class_name
    assert "leading-none" in card_title().class_name
    assert "text-muted-foreground" in card_description().class_name
    assert "p-6" in card_content().class_name
    assert "p-6" in card_footer().class_name


def test_link_emits_anchor_classes():
    a = link("Go", href="/x")
    assert "underline" in a.class_name
    assert "text-primary" in a.class_name


def test_code_inline_classes():
    cls = code("x").class_name
    assert "font-mono" in cls
    assert "bg-muted" in cls


def test_code_block_pre_class():
    blk = code_block("print(1)")
    cls = blk.class_name
    assert "overflow-x-auto" in cls
    assert "bg-zinc-950" in cls


def test_layout_helpers():
    assert "max-w-4xl" in container().class_name
    assert "max-w-2xl" in container(size="sm").class_name
    assert "space-y-4" in section().class_name
    assert "space-y-4" in vstack().class_name
    assert "gap-4" in hstack().class_name
    assert "h-px" in separator().class_name


def test_badge_variants():
    assert "bg-primary" in badge("x").class_name
    assert "bg-secondary" in badge("x", variant="secondary").class_name
    assert "bg-destructive" in badge("x", variant="destructive").class_name
    assert "border-transparent" not in badge("x", variant="outline").class_name


def test_global_css_contains_root_and_dark_tokens():
    css = shadcn_global_css()
    assert ":root {" in css
    assert ".dark {" in css
    for token in (
        "--background",
        "--foreground",
        "--primary",
        "--destructive",
        "--border",
        "--ring",
        "--radius",
    ):
        assert token in css


def test_global_css_size_under_3kb():
    """The theme preflight is the entire CSS users pay vs Radix Themes' 600 KB."""
    css = shadcn_global_css()
    assert len(css) < 3 * 1024  # 3 KB ceiling


def test_tailwind_theme_extends_colors_and_radius():
    theme = shadcn_tailwind_theme()
    extend = theme["extend"]
    for color in ("background", "foreground", "primary", "destructive", "ring"):
        assert color in extend["colors"]
    assert "lg" in extend["borderRadius"]
