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


def _theme_css(**kwargs) -> str:
    return rxe.ExperimentalThemePlugin(**kwargs).get_static_assets()[0][1]


def test_theme_default_is_violet_slate():
    css = _theme_css()
    assert "--violet-9:" in css
    assert "--slate-9:" in css
    assert "--accent-9: var(--violet-9);" in css
    # gray_color="slate" must remap --gray-* like Radix's data-gray-color does
    assert "--gray-9: var(--slate-9);" in css
    assert "--iris-9:" not in css


def test_theme_custom_accent_and_gray():
    css = _theme_css(accent_color="iris", gray_color="sand")
    assert "--iris-9:" in css
    assert "--sand-9:" in css
    assert "--accent-9: var(--iris-9);" in css
    assert "--accent-contrast: var(--iris-contrast);" in css
    assert "--gray-a7: var(--sand-a7);" in css
    assert "--violet-9:" not in css
    assert "--slate-9:" not in css


def test_theme_gray_accent_follows_gray_color():
    css = _theme_css(accent_color="gray", gray_color="sand")
    assert "--accent-9: var(--sand-9);" in css


def test_theme_pure_gray_has_no_self_alias():
    css = _theme_css(gray_color="gray")
    assert "--gray-9: #" in css  # the scale itself
    assert "--gray-9: var(--gray-9);" not in css  # a self-alias would cycle


@pytest.mark.parametrize(
    ("radius", "factor", "full", "thumb"),
    [
        ("none", "0", "0px", "0.5px"),
        ("small", "0.75", "0px", "0.5px"),
        ("medium", "1", "0px", "9999px"),
        ("large", "1.5", "0px", "9999px"),
        ("full", "1.5", "9999px", "9999px"),
    ],
)
def test_theme_radius_tokens(radius, factor, full, thumb):
    css = _theme_css(radius=radius)
    overrides = css[css.rindex(":root, .light {") :]
    assert f"--radius-factor: {factor};" in overrides
    assert f"--radius-full: {full};" in overrides
    assert f"--radius-thumb: {thumb};" in overrides


@pytest.mark.parametrize(
    ("scaling", "factor"),
    [("90%", "0.9"), ("95%", "0.95"), ("100%", "1"), ("105%", "1.05"), ("110%", "1.1")],
)
def test_theme_scaling(scaling, factor):
    css = _theme_css(scaling=scaling)
    assert f"--scaling: {factor};" in css[css.rindex(":root, .light {") :]


def test_theme_ships_dark_and_p3_variants():
    css = _theme_css(accent_color="teal", gray_color="sage")
    assert ".dark" in css
    assert "display-p3" in css
    # dark values of the chosen scales are present, not just light
    dark = css[css.index(".dark") :]
    assert "--teal-9:" in dark
    assert "--sage-9:" in dark


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accent_color": "magenta"},
        {"gray_color": "violet"},
        {"radius": "huge"},
        {"scaling": "150%"},
    ],
)
def test_theme_invalid_options_raise(kwargs):
    with pytest.raises(ValueError, match="expected one of"):
        rxe.ExperimentalThemePlugin(**kwargs)


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
