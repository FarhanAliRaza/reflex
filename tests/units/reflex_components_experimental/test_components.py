"""Smoke tests for the experimental component package."""

import reflex_components_experimental as rxe


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
