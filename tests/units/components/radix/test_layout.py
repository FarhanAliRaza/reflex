"""Tests for Radix Themes layout components."""

from reflex_components_radix.themes.layout.base import LayoutComponent

import reflex as rx


def test_layout_component():
    lc = LayoutComponent.create()
    assert isinstance(lc, LayoutComponent)


def _classes(component) -> str:
    """Flatten a component's ``class_name`` (str or list) into one string.

    Args:
        component: A Reflex component instance.

    Returns:
        A space-joined class-name string for substring matching in asserts.
    """
    raw = component.class_name
    return " ".join(raw) if isinstance(raw, list) else str(raw)


def test_vstack_emits_flex_col_class():
    """Regression: VStack used to declare ``direction`` as a field default,
    so ``flex-col`` was never emitted and the stack rendered as ``flex-row``.
    """
    classes = _classes(rx.vstack())

    assert "flex" in classes.split()
    assert "flex-col" in classes
    assert "items-start" in classes
    assert "gap-[var(--space-3)]" in classes
    assert "rx-Stack" in classes


def test_hstack_emits_flex_row_class():
    classes = _classes(rx.hstack())

    assert "flex-row" in classes
    assert "items-start" in classes
    assert "gap-[var(--space-3)]" in classes


def test_stack_default_align_and_spacing():
    classes = _classes(rx.stack())

    assert "items-start" in classes
    assert "gap-[var(--space-3)]" in classes


def test_vstack_user_props_override_defaults():
    classes = _classes(rx.vstack(align="center", spacing="5"))

    assert "flex-col" in classes
    assert "items-center" in classes
    assert "gap-[var(--space-5)]" in classes
    assert "items-start" not in classes
    assert "gap-[var(--space-3)]" not in classes


def test_hstack_direction_override():
    """A user-supplied ``direction`` on hstack must win over the default."""
    classes = _classes(rx.hstack(direction="column-reverse"))

    assert "flex-col-reverse" in classes
    assert "flex-row" not in classes
