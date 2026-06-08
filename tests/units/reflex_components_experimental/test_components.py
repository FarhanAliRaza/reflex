"""Smoke tests for the experimental component package."""

import reflex_components_experimental as rxe

import reflex as rx


def test_public_api_present():
    for name in [
        "button",
        "badge",
        "card",
        "text",
        "heading",
        "switch",
        "checkbox",
        "radio",
        "radio_group",
        "slider",
        "progress",
        "table",
        "tabs",
        "menu",
        "dialog",
        "select",
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
    assert callable(rxe.tabs.tab)
    assert callable(rxe.menu.item)
    assert callable(rxe.slider)
    assert callable(rxe.select.trigger)
    assert callable(rxe.dialog.popup)
    assert callable(rxe.accordion.panel)


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


def test_switch_wraps_base_ui():
    # The accessible switch is backed by Base UI (role=switch at runtime) and
    # declares the headless package as a dependency.
    sw = rxe.switch(default_checked=True)
    assert sw.tag == "Switch.Root"
    assert any("@base-ui/react" in d for d in sw.lib_dependencies)
    render = str(sw.render())
    assert "Switch.Root" in render
    assert "Switch.Thumb" in render
    # checked styling tracks Base UI state rather than being hard-coded.
    assert "data-[checked]" in render


def test_interactive_components_render():
    # Every compound widget composes without error.
    comps = [
        rxe.checkbox(default_checked=True),
        rxe.radio_group(rxe.radio("a"), rxe.radio("b"), default_value="a"),
        rxe.slider(default_value=40),
        rxe.progress(value=60),
        rxe.tabs.root(
            rxe.tabs.list(rxe.tabs.tab("One", "1"), rxe.tabs.tab("Two", "2")),
            rxe.tabs.panel(rx.el.div("p1"), value="1"),
            default_value="1",
        ),
        rxe.dialog.root(
            rxe.dialog.trigger("open"),
            rxe.dialog.portal(rxe.dialog.popup(rxe.dialog.title("T"))),
        ),
        rxe.menu.root(
            rxe.menu.trigger("m"),
            rxe.menu.portal(
                rxe.menu.positioner(rxe.menu.popup(rxe.menu.item("Item 1")))
            ),
        ),
        rxe.select.root(
            rxe.select.trigger(rxe.select.value(placeholder="Pick")),
            rxe.select.portal(
                rxe.select.positioner(
                    rxe.select.popup(
                        rxe.select.item(rxe.select.item_text("A"), value="a")
                    )
                )
            ),
        ),
    ]
    for c in comps:
        assert str(c.render())
