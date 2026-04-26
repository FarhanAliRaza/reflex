"""Unit tests for the cva-style variants helper."""

from __future__ import annotations

import pytest
from reflex_components_shadcn._variants import cn, variants


def test_variants_applies_base_and_defaults():
    resolve = variants(
        base="base-x",
        defaults={"variant": "primary"},
        variant={"primary": "p-class", "secondary": "s-class"},
    )
    assert resolve() == "base-x p-class"


def test_variants_overrides_default_per_call():
    resolve = variants(
        base="base",
        defaults={"variant": "primary"},
        variant={"primary": "p", "secondary": "s"},
    )
    assert resolve(variant="secondary") == "base s"


def test_variants_combines_multiple_groups():
    resolve = variants(
        base="b",
        defaults={"variant": "default", "size": "md"},
        variant={"default": "v-default", "outline": "v-outline"},
        size={"sm": "size-sm", "md": "size-md", "lg": "size-lg"},
    )
    assert resolve(variant="outline", size="lg") == "b v-outline size-lg"


def test_variants_unknown_key_raises():
    resolve = variants(
        base="b",
        defaults={"variant": "default"},
        variant={"default": "v-default"},
    )
    with pytest.raises(KeyError, match="variant='ghost'"):
        resolve(variant="ghost")


def test_variants_skips_group_without_default():
    """No default + no caller selection = group is skipped silently."""
    resolve = variants(
        base="b",
        defaults={"variant": "default"},  # no size default
        variant={"default": "v"},
        size={"sm": "s"},
    )
    assert resolve() == "b v"
    assert resolve(size="sm") == "b v s"


def test_cn_drops_empty_and_none():
    assert cn("a", None, "", "b") == "a b"


def test_cn_strips_whitespace():
    assert cn("  a  ", "b ") == "a b"
