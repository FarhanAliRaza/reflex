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


@pytest.mark.parametrize("variant", ["solid", "soft", "surface"])
def test_button_filled_variants_do_not_emit_transparent_background(variant):
    render = str(rxe.button("Go", variant=variant).render())
    assert "bg-transparent" not in render


@pytest.mark.parametrize("variant", ["outline", "ghost"])
def test_button_unfilled_variants_emit_transparent_background(variant):
    render = str(rxe.button("Go", variant=variant).render())
    assert "bg-transparent" in render


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


@pytest.mark.parametrize("spacing", [str(n) for n in range(10)])
def test_layout_spacing_alias_matches_radix_api(spacing):
    for comp in (rxe.flex(spacing=spacing), rxe.grid(spacing=spacing)):
        render = str(comp.render())
        if spacing == "0":
            assert "--space-0" not in render
            assert "gap-0" in render
        else:
            assert f"gap-[var(--space-{spacing})]" in render


def test_grid_axis_spacing_aliases_match_radix_api():
    render = str(rxe.grid(spacing_x="2", spacing_y="4").render())
    assert "gap-x-[var(--space-2)]" in render
    assert "gap-y-[var(--space-4)]" in render


def test_flex_alignment_overrides_do_not_emit_conflicting_defaults():
    render = str(rxe.flex(justify="between", align="center").render())
    assert "justify-between" in render
    assert "items-center" in render
    assert "justify-start" not in render
    assert "items-stretch" not in render


def test_grid_alignment_overrides_do_not_emit_conflicting_defaults():
    render = str(rxe.grid(justify="center", align="center").render())
    assert "justify-center" in render
    assert "items-center" in render
    assert "justify-start" not in render
    assert "items-stretch" not in render


@pytest.mark.parametrize(
    "trigger",
    [
        rxe.dialog.trigger,
        rxe.alert_dialog.trigger,
        rxe.popover.trigger,
        rxe.hover_card.trigger,
        rxe.tooltip.trigger,
        rxe.menu.trigger,
    ],
)
def test_overlay_triggers_render_native_button_child_as_trigger(trigger):
    rendered = trigger(rxe.button("Open")).render()
    assert rendered["children"] == []
    assert any(str(prop).startswith("render:") for prop in rendered["props"])


def test_menu_trigger_plain_content_stays_native_trigger():
    rendered = rxe.menu.trigger("Open").render()
    assert rendered["children"]
    assert not any(str(prop).startswith("render:") for prop in rendered["props"])


def test_select_item_infers_label_from_item_text():
    render = str(
        rxe.select.item(
            rxe.select.item_text("Developer experience"), value="dx"
        ).render()
    )
    assert 'label:"Developer experience"' in render


def test_select_high_level_api_matches_radix_shape():
    assert callable(rxe.select)
    assert callable(rxe.select.trigger)
    render = str(
        rxe.select(
            ["Performance", "Accessibility", "Developer experience"],
            default_value="Developer experience",
            placeholder="Focus area",
        ).render()
    )
    assert "Select.Root" in render
    assert "Developer experience" in render
    assert "Focus area" in render
    assert 'value:"dx"' not in render


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


class _VarState(rx.State):
    """State for driving size/variant as Vars in tests."""

    v: str = "solid"
    s: str = "2"


def test_button_variant_var_enumerates_all_branches():
    # A state-driven variant must compile to a match whose branches carry
    # every variant's full class string as a literal (Tailwind-scannable).
    render = str(rxe.button("x", variant=_VarState.v).render())
    for token in (
        "bg-[var(--accent-9)]",  # solid
        "bg-[var(--accent-a3)]",  # soft
        "shadow-[inset_0_0_0_1px_var(--accent-a8)]",  # outline
        "bg-[var(--accent-surface)]",  # surface
        "-mx-[var(--space-2)]",  # ghost box model
    ):
        assert token in render, token


def test_button_size_and_variant_var_cross_product():
    render = str(rxe.button("x", size=_VarState.s, variant=_VarState.v).render())
    # every size's height token appears (non-ghost branches)
    for space in ("--space-5", "--space-6", "--space-7", "--space-8"):
        assert f"h-[var({space})]" in render, space
    # ghost branches for multiple sizes appear too
    assert "-mx-[var(--space-2)]" in render
    assert "-mx-[var(--space-3)]" in render


def test_button_static_path_unchanged_by_var_support():
    # Plain strings must still produce a single static class literal,
    # no match and no cn.
    render = str(rxe.button("x", size="3", variant="outline").render())
    assert "switch" not in render
    assert "cn(" not in render
    assert "shadow-[inset_0_0_0_1px_var(--accent-a8)]" in render


def test_button_var_with_class_name_override_merges():
    render = str(rxe.button("x", variant=_VarState.v, class_name="bg-red-500").render())
    assert "bg-red-500" in render
    assert "cn(" in render


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
    # The experimental adapter must strip reflex-components-internal defaults.
    assert "bg-secondary-4" not in render
    assert "translate-x-3" not in render


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
