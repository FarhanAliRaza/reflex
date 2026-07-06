"""Smoke tests for the experimental component package."""

import pytest
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
    # solid variant references the accent-9 token; without a user override the
    # class stays a plain literal (no runtime cn() call).
    assert "accent-9" in render
    assert "cn(" not in render


def test_class_name_override_is_merged():
    render = str(rxe.button("x", class_name="bg-red-500").render())
    # a user override switches to the runtime cn() merge path
    assert "bg-red-500" in render
    assert "cn(" in render


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


# Every (component, sizes, variants) combination that is valid in the Radix
# Themes API must at least construct and render — regression guard against
# dict-lookup KeyErrors on values the real rx.* components accept.
_RADIX_RANGES = [
    (
        lambda s, v: rxe.button("x", size=s, variant=v),
        "1234",
        "solid soft outline surface ghost",
    ),
    (
        lambda s, v: rxe.badge("x", size=s, variant=v),
        "123",
        "solid soft surface outline",
    ),
    (lambda s, v: rxe.callout("x", size=s, variant=v), "123", "soft surface outline"),
    (lambda s, v: rxe.card("x", size=s), "12345", None),
    (lambda s, v: rxe.avatar("A", size=s, variant=v), "123456789", "solid soft"),
    (lambda s, v: rxe.separator(size=s), "1234", None),
    (lambda s, v: rxe.spinner(size=s), "123", None),
    (lambda s, v: rxe.table.cell("x", size=s), "123", None),
    (lambda s, v: rxe.table.header_cell("x", size=s), "123", None),
    (lambda s, v: rxe.text_field(size=s, variant=v), "123", "classic surface soft"),
    (lambda s, v: rxe.text_area(size=s, variant=v), "123", "classic surface soft"),
    (
        lambda s, v: rxe.code("x", size=s, variant=v),
        "123456789",
        "solid soft outline ghost",
    ),
    (
        lambda s, v: rxe.text("x", size=s, weight=v),
        "123456789",
        "light regular medium bold",
    ),
    (lambda s, v: rxe.heading("x", size=s), "123456789", None),
    (lambda s, v: rxe.link("x", size=s), "123456789", None),
    (lambda s, v: rxe.blockquote("x", size=s), "123456789", None),
    (lambda s, v: rxe.container("x", size=s), "1234", None),
    (lambda s, v: rxe.section("x", size=s), "123", None),
    (lambda s, v: rxe.switch(size=s), "123", None),
    (lambda s, v: rxe.checkbox(size=s), "123", None),
    (lambda s, v: rxe.radio("a", size=s), "123", None),
    (lambda s, v: rxe.slider(size=s), "123", None),
    (lambda s, v: rxe.progress(size=s), "123", None),
    (lambda s, v: rxe.scroll_area(rx.el.div(), size=s), "123", None),
]


@pytest.mark.parametrize(
    ("factory", "size", "variant"),
    [
        (factory, size, variant)
        for factory, sizes, variants in _RADIX_RANGES
        for size in sizes
        for variant in (variants.split() if variants else [None])
    ],
)
def test_all_valid_radix_values_render(factory, size, variant):
    assert str(factory(size, variant).render())


@pytest.mark.parametrize("gap", [str(n) for n in range(10)])
def test_layout_gap_range(gap):
    # Radix accepts gap "0"-"9"; "0" maps to a literal 0, not a space token.
    for comp in (rxe.flex(gap=gap), rxe.grid(gap=gap)):
        render = str(comp.render())
        if gap == "0":
            assert "--space-0" not in render
            assert "gap-0" in render
        else:
            assert f"--space-{gap}" in render


def test_theme_defines_all_referenced_tokens():
    # Every var(--token) referenced by a component class string must be
    # defined in the shipped theme (or be a component-local `[--x:...]` var).
    import re
    from pathlib import Path

    import reflex_components_experimental

    pkg = Path(reflex_components_experimental.__file__).parent
    css = rxe.ExperimentalThemePlugin().get_static_assets()[0][1]
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    local_vars = set()
    referenced = set()
    for py in pkg.rglob("*.py"):
        src = py.read_text()
        local_vars |= set(re.findall(r"\[(--[\w-]+):", src))
        # var(--x, fallback) references are fine undefined; only flag var(--x)
        referenced |= set(re.findall(r"var\((--[\w-]+)\)", src))
    # provided by Tailwind/runtime, not the theme
    external = {"--transform-origin"}
    missing = referenced - defined - local_vars - external
    assert not missing, (
        f"tokens referenced but undefined in theme.css: {sorted(missing)}"
    )


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
