"""Smoke tests for the experimental component package."""

import reflex_components_experimental as rxe

import reflex as rx


class _SwitchState(rx.State):
    on: bool = False


def test_public_api_present():
    for name in [
        "button",
        "badge",
        "card",
        "text",
        "heading",
        "switch",
        "checkbox",
        "table",
        "tabs",
        "menu",
        "dialog",
        "select",
        "slider",
        "ExperimentalThemePlugin",
        "cn",
    ]:
        assert hasattr(rxe, name), name


def test_button_renders_token_classes():
    render = str(rxe.button("Go", variant="solid", size="3").render())
    # solid variant references the accent-9 token; cn() wires override-merge.
    assert "accent-9" in render
    assert "cn(" in render


def test_class_name_override_is_merged():
    render = str(rxe.button("x", class_name="bg-red-500").render())
    assert "bg-red-500" in render


def test_namespaces_resolve():
    assert callable(rxe.table.cell)
    assert callable(rxe.tabs.trigger)
    assert callable(rxe.menu.item)
    assert callable(rxe.slider.track)
    assert callable(rxe.select.content)


def test_switch_animates_thumb():
    # The thumb glides like Radix (single persistent element + transition), so a
    # state change is animated rather than snapping.
    render = str(rxe.switch(checked=True).render())
    assert "cubic-bezier" in render
    assert "data-state" in render


def test_switch_checked_accepts_reactive_var():
    # A reactive Var must drive the switch; the presentational impl raised here.
    render = str(rxe.switch(checked=_SwitchState.on).render())
    assert "data-state" in render


def test_avatar_fallback_has_background_and_font():
    # The fallback must render a tinted tile with Radix's typography, not a bare
    # letter: a variant background plus the per-size one-letter font size.
    render = str(rxe.avatar("L", size="3").render())
    assert "accent-a3" in render  # soft (default) background
    assert "font-size-4" in render  # one-letter font size for size 3


def test_theme_plugin():
    p = rxe.ExperimentalThemePlugin()
    assert p.get_stylesheet_paths() == ("./experimental-theme.css",)
    assert any("clsx-for-tailwind" in d for d in p.get_frontend_dependencies())
    assets = p.get_static_assets()
    assert assets
    assert str(assets[0][0]).endswith("experimental-theme.css")
    # the shipped theme defines the Radix-derived design tokens
    assert "--accent-9" in assets[0][1]
    assert "--space-3" in assets[0][1]
