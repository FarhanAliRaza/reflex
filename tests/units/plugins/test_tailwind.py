from pathlib import Path

import pytest
from reflex_base.config import Config
from reflex_base.plugins import tailwind_v3, tailwind_v4
from reflex_base.plugins.shared_tailwind import TailwindConfig


@pytest.mark.parametrize("module", [tailwind_v3, tailwind_v4])
def test_compile_root_style_omits_radix_when_disabled(module):
    """Tailwind root styles should omit the Radix import when disabled."""
    _, code = module.compile_root_style(include_radix_themes=False)

    assert "@radix-ui/themes/styles.css" not in code


@pytest.mark.parametrize("module", [tailwind_v3, tailwind_v4])
def test_add_tailwind_to_css_file_inserts_import_without_radix(module):
    """Tailwind should still be added when the root stylesheet has no Radix import."""
    css = (
        "@layer __reflex_base;\n"
        "@import url('./__reflex_style_reset.css');\n"
        "@import url('./style.css');"
    )

    updated_css = module.add_tailwind_to_css_file(
        css,
        include_radix_themes=False,
    )

    assert updated_css.splitlines() == [
        "@layer __reflex_base;",
        "@import url('./__reflex_style_reset.css');",
        "@import url('./tailwind.css');",
        "@import url('./style.css');",
    ]


def test_v3_compile_root_style_keeps_expected_output_path():
    """Tailwind v3 should continue writing to the shared tailwind.css path."""
    output_path, _ = tailwind_v3.compile_root_style(include_radix_themes=False)

    assert output_path == str(Path("styles") / "tailwind.css")


@pytest.mark.parametrize("module", [tailwind_v3, tailwind_v4])
def test_compile_config_includes_astro_content_paths(module, monkeypatch):
    """When frontend_target='astro', Tailwind should also scan Astro output paths.

    In islands mode, static HTML is emitted inline in ``src/pages/<route>.astro``
    files and user-authored React components live under ``public/components/``.
    Without these paths in Tailwind's content config, the classes used there
    are missing from the generated CSS bundle and the page renders unstyled.
    """
    cfg = Config(app_name="test_app", frontend_target="astro")
    monkeypatch.setattr("reflex_base.config.get_config", lambda: cfg)

    _, generated = module.compile_config(TailwindConfig())

    assert "./src/pages/**/*.astro" in generated
    assert "./public/components/**/*.{js,ts,jsx,tsx}" in generated


@pytest.mark.parametrize("module", [tailwind_v3, tailwind_v4])
def test_compile_config_omits_astro_paths_for_react_router(module, monkeypatch):
    """React-router target should keep the original two-path content list."""
    cfg = Config(app_name="test_app", frontend_target="react_router")
    monkeypatch.setattr("reflex_base.config.get_config", lambda: cfg)

    _, generated = module.compile_config(TailwindConfig())

    assert "./src/pages/**/*.astro" not in generated
    assert "./public/components/**/*.{js,ts,jsx,tsx}" not in generated
