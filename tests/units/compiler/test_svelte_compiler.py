from pathlib import Path

import pytest
from reflex_base import constants
from reflex_base.utils.exceptions import UnsupportedFrontendTargetError
from reflex_base.utils.imports import ImportVar

import reflex as rx
from reflex.app import UnevaluatedPage
from reflex.compiler import compiler, svelte as svelte_compiler


def _svelte_config() -> rx.Config:
    return rx.Config(
        app_name="test",
        frontend_target=constants.FrontendTarget.SVELTEKIT,
    )


def test_svelte_normalize_imports_rewrites_react_libraries():
    imports = {
        "@radix-ui/themes@3.3.0": [ImportVar(tag="Button")],
        "react-router": [ImportVar(tag="Link")],
        "react": [ImportVar(tag="useContext")],
    }

    normalized = svelte_compiler.normalize_imports(imports)

    assert set(normalized) == {
        "$lib/reflex/components/radix-themes.js",
        "$lib/reflex/components/router.js",
    }


def test_svelte_normalize_imports_rejects_custom_react_modules():
    with pytest.raises(UnsupportedFrontendTargetError):
        svelte_compiler.normalize_imports({
            "$/utils/components": [ImportVar(tag="Widget")]
        })


def test_compile_page_svelte_stateful(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("reflex.compiler.compiler.get_config", _svelte_config)

    class State(rx.State):
        count: int = 1

        def increment(self):
            self.count += 1

    component = rx.container(
        rx.color_mode.button(position="top-right"),
        rx.text(State.count),
        rx.button("Increment", on_click=State.increment),
    )

    output_path, code = compiler.compile_page("index", component)

    normalized_output_path = output_path.replace("\\", "/")
    assert normalized_output_path.endswith(".web/src/routes/+page.svelte")
    assert "$lib/reflex/components/radix-themes.js" in code
    assert "const resolvedColorMode = $derived(runtime.resolvedColorMode);" in code
    assert 'runtime.getStateByAlias("' in code
    assert 'ReflexEvent("' in code
    assert "onclick={" in code


def test_compile_page_svelte_hoists_head_and_renders_control_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("reflex.compiler.compiler.get_config", _svelte_config)

    page = UnevaluatedPage(
        route="index",
        component=lambda: rx.fragment(
            rx.cond(True, rx.text("yes"), rx.text("no")),
            rx.foreach(["a", "b"], lambda item: rx.text(item)),
            rx.match("a", ("a", rx.text("A")), rx.text("B")),
        ),
    )

    compiled = compiler.compile_unevaluated_page("index", page, {}, None)
    _, code = compiler.compile_page("index", compiled)

    assert "<svelte:head>" in code
    assert "{#if true}" in code
    assert "{#each (" in code
    assert "{@const __reflexMatch1 =" in code
    assert "<title>" in code


def test_compile_page_svelte_translates_ref_hooks_and_landing_page_components(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("reflex.compiler.compiler.get_config", _svelte_config)

    component = rx.section(
        rx.container(
            rx.vstack(
                rx.badge("Features", variant="surface", size="2", radius="full"),
                rx.hstack(
                    rx.link("Features", href="#features", underline="none", size="3"),
                    rx.avatar(fallback="A", size="2", radius="full"),
                    spacing="3",
                ),
                rx.grid(
                    rx.card(
                        rx.vstack(
                            rx.icon("hexagon", size=20, color="var(--accent-9)"),
                            rx.heading("Acme", size="5", weight="bold"),
                            rx.separator(size="4"),
                            rx.text("Built with SvelteKit", size="3"),
                        ),
                        size="3",
                    ),
                    columns={"base": "1", "md": "2"},
                    spacing="5",
                    width="100%",
                ),
                spacing="5",
            ),
            size="4",
        ),
        id="features",
    )

    _, code = compiler.compile_page("index", component)

    assert 'const ref_features = runtime.createRef("ref_features");' in code
    assert "$lib/reflex/components/radix-themes.js" in code
    assert "$lib/reflex/components/lucide.js" in code
    assert "RadixThemesAvatar" in code
    assert "RadixThemesGrid" in code
    assert "RadixThemesSeparator" in code
    assert "ref={ref_features}" in code

def test_compile_stylesheets_svelte_uses_minimal_radix_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project = tmp_path / "test_project"
    project.mkdir()
    assets_dir = project / "assets"
    assets_dir.mkdir()
    (assets_dir / "style.css").write_text("body { color: red; }")

    config = _svelte_config()
    monkeypatch.setattr("reflex.compiler.compiler.get_config", lambda: config)
    monkeypatch.setattr("reflex.compiler.compiler.Path.cwd", lambda: project)
    monkeypatch.setattr(
        "reflex.compiler.compiler.get_web_dir",
        lambda: project / constants.Dirs.WEB,
    )
    monkeypatch.setattr(
        "reflex.compiler.utils.get_web_dir",
        lambda: project / constants.Dirs.WEB,
    )

    _, code = compiler.compile_root_stylesheet(["/style.css"])

    assert "@radix-ui/themes/styles.css" not in code
    assert "@radix-ui/themes/tokens.css" in code
    assert "@radix-ui/themes/layout/tokens.css" not in code
    assert "@import url('./style.css');" in code


def test_compile_page_svelte_converts_html_css_attr_to_style(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("reflex.compiler.compiler.get_config", _svelte_config)

    component = rx.el.div(
        rx.el.p("hello"),
        style={"min_height": "100vh", "background": "red"},
    )

    _, code = compiler.compile_page("index", component)

    assert (
        'import { styleObjectToString } from "$lib/reflex/components/style.js";' in code
    )
    assert "<div style={" in code
    assert "<div css={" not in code
