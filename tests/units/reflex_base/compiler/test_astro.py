"""Unit tests for the Astro target codegen module.

Covers ``packages/reflex-base/src/reflex_base/compiler/astro.py``:
- route-to-file-path translator
- Astro page / layout / config templates
- per-mode emission rules
- the high-level ``emit_astro_artifacts`` aggregator
- inline color-mode head script
"""

from __future__ import annotations

import pytest
from reflex_base.compiler.astro import (
    AstroEmitterInput,
    AstroIsland,
    AstroPageArtifact,
    astro_color_mode_inline_script,
    astro_config_template,
    astro_island_module_path,
    astro_layout_template,
    astro_page_root_island_template,
    astro_page_template,
    astro_route_to_file_path,
    emit_astro_artifacts,
    emit_astro_config,
    emit_astro_layout,
    emit_astro_page,
    emit_astro_page_root_island,
)
from reflex_base.utils.exceptions import CompileError


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("/", "src/pages/index.astro"),
        ("/foo", "src/pages/foo.astro"),
        ("/foo/bar", "src/pages/foo/bar.astro"),
        ("/blog/[slug]", "src/pages/blog/[slug].astro"),
        ("/docs/[...path]", "src/pages/docs/[...path].astro"),
        ("/blog/[[slug]]", "src/pages/blog/[slug].astro"),
        ("/docs/[[...path]]", "src/pages/docs/[...path].astro"),
    ],
)
def test_astro_route_to_file_path_table(route: str, expected: str):
    assert astro_route_to_file_path(route) == expected


def test_astro_route_to_file_path_rejects_relative():
    with pytest.raises(CompileError, match="must start with"):
        astro_route_to_file_path("foo")


def test_astro_island_module_path_table():
    assert (
        astro_island_module_path("/blog/[slug]", "Sidebar")
        == "src/reflex/islands/blog/slug/Sidebar.tsx"
    )
    assert (
        astro_island_module_path("/", "PageRoot")
        == "src/reflex/islands/index/PageRoot.tsx"
    )


def test_astro_layout_template_minimal():
    layout = astro_layout_template()
    assert "<!doctype html>" in layout
    assert "<slot />" in layout
    assert "Astro.props" in layout


def test_astro_config_template_static_output():
    config = astro_config_template()
    assert 'output: "static"' in config
    assert "@astrojs/react" in config
    assert "react()" in config
    # Defaults: no site / base lines.
    assert "site:" not in config
    assert "base:" not in config


def test_astro_config_template_with_site_base_port():
    config = astro_config_template(site="https://example.com", base="/docs", port=3000)
    assert '"https://example.com"' in config
    assert '"/docs"' in config
    assert "port: 3000," in config


def test_astro_page_template_app_mode_includes_client_load():
    page = astro_page_template(
        render_mode="app",
        title="Home",
        page_root_import="../reflex/islands/index/PageRoot.tsx",
    )
    assert "<PageRoot client:load />" in page
    assert "../reflex/islands/index/PageRoot.tsx" in page
    assert '"Home"' in page
    assert "<Layout title={title}>" in page


def test_astro_page_template_static_mode_no_react():
    page = astro_page_template(
        render_mode="static",
        title="About",
        static_html="<h1>About</h1>",
    )
    assert "client:load" not in page
    assert "client:idle" not in page
    assert "client:visible" not in page
    assert "client:only" not in page
    assert "<h1>About</h1>" in page


def test_astro_page_template_islands_mode_emits_directives():
    islands = (
        AstroIsland(
            component_name="ThemeSwitcher",
            module_path="../reflex/islands/index/ThemeSwitcher.tsx",
            directive="client:idle",
        ),
        AstroIsland(
            component_name="Subscribe",
            module_path="../reflex/islands/index/Subscribe.tsx",
            directive="client:visible",
        ),
    )
    page = astro_page_template(
        render_mode="islands",
        title="Landing",
        static_html="<main>hello</main>",
        islands=islands,
    )
    assert "<ThemeSwitcher client:idle />" in page
    assert "<Subscribe client:visible />" in page
    assert "<main>hello</main>" in page
    assert "ThemeSwitcher" in page  # imported in frontmatter


def test_astro_page_template_islands_mode_dedupes_imports():
    islands = (
        AstroIsland(
            component_name="A",
            module_path="../mod.tsx",
            directive="client:load",
        ),
        AstroIsland(
            component_name="A",
            module_path="../mod.tsx",
            directive="client:visible",
        ),
    )
    page = astro_page_template(render_mode="islands", title="x", islands=islands)
    # Only one import line for A.
    assert page.count("import { A }") == 1
    # But both instances render (different directives).
    assert "<A client:load />" in page
    assert "<A client:visible />" in page


def test_astro_page_template_islands_mode_client_only():
    islands = (
        AstroIsland(
            component_name="DataTable",
            module_path="../mod.tsx",
            directive="client:only",
        ),
    )
    page = astro_page_template(render_mode="islands", title="x", islands=islands)
    assert '<DataTable client:only="react" />' in page


def test_astro_page_template_islands_mode_with_media_query():
    islands = (
        AstroIsland(
            component_name="MobileNav",
            module_path="../mod.tsx",
            directive="client:visible",
            media="(max-width: 768px)",
        ),
    )
    page = astro_page_template(render_mode="islands", title="x", islands=islands)
    assert "client:visible=" in page
    assert "(max-width: 768px)" in page


def test_astro_page_template_app_requires_page_root_import():
    with pytest.raises(CompileError, match="page_root_import"):
        astro_page_template(render_mode="app", title="x")


def test_astro_page_template_static_rejects_islands():
    islands = (
        AstroIsland(
            component_name="A", module_path="../m.tsx", directive="client:load"
        ),
    )
    with pytest.raises(CompileError, match="static"):
        astro_page_template(
            render_mode="static",
            title="x",
            islands=islands,
        )


def test_astro_page_template_invalid_render_mode():
    with pytest.raises(CompileError, match="Invalid render_mode"):
        astro_page_template(render_mode="ssr", title="x")  # pyright: ignore[reportArgumentType]


def test_astro_page_template_static_paths_round_trip():
    page = astro_page_template(
        render_mode="static",
        title="Post",
        static_html="<h1>post</h1>",
        static_paths=[{"slug": "a"}, {"slug": "b"}],
    )
    assert "getStaticPaths" in page
    assert '"slug": "a"' in page
    assert '"slug": "b"' in page


def test_astro_page_root_island_template_default_export():
    src = astro_page_root_island_template(page_module_import="../page.jsx")
    assert "import Page from" in src
    assert "../page.jsx" in src
    assert "export default function PageRoot" in src
    assert "<Page />" in src


def test_astro_page_root_island_template_named_export():
    src = astro_page_root_island_template(
        page_module_import="../page.jsx",
        page_module_default_export=False,
    )
    assert "import { Component as Page }" in src


def test_emit_astro_page_returns_artifact():
    artifact = emit_astro_page(
        AstroEmitterInput(
            route="/",
            title="Home",
            render_mode="app",
            page_module_import="../reflex/islands/index/PageRoot.tsx",
        )
    )
    assert isinstance(artifact, AstroPageArtifact)
    assert artifact.path == "src/pages/index.astro"
    assert "client:load" in artifact.contents


def test_emit_astro_page_static_route_with_dynamic_path():
    artifact = emit_astro_page(
        AstroEmitterInput(
            route="/blog/[slug]",
            title="post",
            render_mode="static",
            static_html="<article>x</article>",
            static_paths=({"slug": "a"}, {"slug": "b"}),
        )
    )
    assert artifact.path == "src/pages/blog/[slug].astro"
    assert "getStaticPaths" in artifact.contents


def test_emit_astro_layout_artifact():
    artifact = emit_astro_layout()
    assert artifact.path == "src/layouts/Layout.astro"
    assert "<slot />" in artifact.contents


def test_emit_astro_config_artifact():
    artifact = emit_astro_config(site="https://example.com", base="/docs")
    assert artifact.path == "astro.config.mjs"
    assert '"https://example.com"' in artifact.contents


def test_emit_astro_page_root_island_artifact():
    artifact = emit_astro_page_root_island(
        route="/blog/[slug]",
        page_module_import="../page.jsx",
    )
    assert artifact.path == "src/reflex/islands/blog/slug/PageRoot.tsx"
    assert "import Page from" in artifact.contents


def test_emit_astro_artifacts_aggregates_layout_config_and_pages():
    pages = [
        AstroEmitterInput(
            route="/",
            title="Home",
            render_mode="app",
            page_module_import="../reflex/islands/index/PageRoot.tsx",
        ),
        AstroEmitterInput(
            route="/about",
            title="About",
            render_mode="static",
            static_html="<h1>about</h1>",
        ),
    ]
    artifacts = emit_astro_artifacts(pages, base="/docs")
    paths = [a.path for a in artifacts]
    # The layout and config land first.
    assert "src/layouts/Layout.astro" in paths
    assert "astro.config.mjs" in paths
    # Each page lands at its computed path.
    assert "src/pages/index.astro" in paths
    assert "src/pages/about.astro" in paths
    # The app-mode page also gets its PageRoot island module.
    assert "src/reflex/islands/index/PageRoot.tsx" in paths
    # The static-mode page does NOT get an island module.
    assert "src/reflex/islands/about/PageRoot.tsx" not in paths


def test_emit_astro_artifacts_includes_static_html():
    pages = [
        AstroEmitterInput(
            route="/about",
            title="About",
            render_mode="static",
            static_html="<h1>about page</h1>",
        ),
    ]
    artifacts = emit_astro_artifacts(pages)
    page_artifact = next(a for a in artifacts if a.path == "src/pages/about.astro")
    assert "<h1>about page</h1>" in page_artifact.contents


def test_emit_astro_artifacts_islands_page_no_page_root_island():
    """An islands-mode page should not get a PageRoot module.

    The runtime boots inside the first stateful island, not in a
    page-root wrapper.
    """
    pages = [
        AstroEmitterInput(
            route="/landing",
            title="Landing",
            render_mode="islands",
            islands=(
                AstroIsland(
                    component_name="Subscribe",
                    module_path="../reflex/islands/landing/Subscribe.tsx",
                    directive="client:visible",
                ),
            ),
        ),
    ]
    artifacts = emit_astro_artifacts(pages)
    paths = [a.path for a in artifacts]
    assert "src/reflex/islands/landing/PageRoot.tsx" not in paths


def test_astro_color_mode_inline_script_default_is_system():
    """Default fallback is 'system' (uses prefers-color-scheme)."""
    src = astro_color_mode_inline_script()
    assert "prefers-color-scheme: dark" in src
    assert "data-color-mode" in src
    assert "reflex-color-mode" in src
    assert "color_mode" in src


def test_astro_color_mode_inline_script_explicit_default():
    src = astro_color_mode_inline_script(default_color_mode="light")
    assert '"light"' in src


def test_astro_color_mode_inline_script_custom_keys():
    src = astro_color_mode_inline_script(cookie_name="rx-color", storage_key="rx_color")
    assert "rx-color" in src
    assert "rx_color" in src


def test_astro_layout_template_includes_color_mode_script_when_provided():
    layout = astro_layout_template(color_mode_script=astro_color_mode_inline_script())
    assert "<script is:inline>" in layout
    assert "data-color-mode" in layout


def test_astro_layout_template_no_color_mode_script_by_default():
    layout = astro_layout_template()
    assert "<script is:inline>" not in layout


def test_emit_astro_layout_inline_color_mode_default_on():
    artifact = emit_astro_layout()
    assert "<script is:inline>" in artifact.contents
    assert "data-color-mode" in artifact.contents


def test_emit_astro_layout_inline_color_mode_off():
    artifact = emit_astro_layout(inline_color_mode_script=False)
    assert "<script is:inline>" not in artifact.contents
