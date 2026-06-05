"""Tests for per-component Radix CSS chunk imports."""

from reflex_components_radix.css_split import radix_chunk_name
from reflex_components_radix.plugin import RADIX_CSS_SPLIT_ATTR

import reflex as rx
from reflex.compiler import utils as compiler_utils


def test_chunk_name_matches_radix_source_naming():
    """Component tags map to Radix's kebab-case source file stems."""
    assert radix_chunk_name("Button") == "button"
    assert radix_chunk_name("IconButton") == "icon-button"
    assert radix_chunk_name("TextField.Root") == "text-field"
    assert radix_chunk_name("DropdownMenu.Content") == "dropdown-menu"


def test_unmarked_component_emits_no_css_imports():
    """Without splitting, a Radix component imports no CSS chunks (default)."""
    button = rx.button("hi")
    assert not any(lib.endswith(".css") for lib in button._get_all_imports())


def test_marked_component_imports_shared_and_own_chunk():
    """A split-marked component side-effect-imports the shared base and its chunk."""
    button = rx.button("hi")
    setattr(button, RADIX_CSS_SPLIT_ATTR, True)

    imports = button._get_all_imports()
    assert "$/styles/radix/_shared.css" in imports
    assert "$/styles/radix/button.css" in imports

    compiled = compiler_utils.compile_imports(imports)
    chunk = next(i for i in compiled if i["lib"] == "$/styles/radix/button.css")
    # A side-effect import: no default and no named bindings -> import "...".
    assert chunk["default"] == ""
    assert chunk["rest"] == []


def test_split_imports_propagate_through_tree():
    """A marked component nested in a tree contributes its CSS imports upward."""
    button = rx.button("hi")
    setattr(button, RADIX_CSS_SPLIT_ATTR, True)
    tree = rx.box(rx.text("x"), button)
    assert "$/styles/radix/button.css" in tree._get_all_imports()


def test_plugin_emits_split_chunks_as_static_assets(tmp_path, monkeypatch):
    """The plugin reads the installed bundle and writes per-component chunks."""
    from reflex_components_radix.plugin import RadixThemesPlugin

    import reflex.utils.prerequisites as prerequisites

    web = tmp_path / ".web"
    package = web / "node_modules" / "@radix-ui" / "themes"
    components = package / "src" / "components"
    components.mkdir(parents=True)
    (package / "styles.css").write_text(
        ":root { --x: 1; }\n.rt-Button { color: red; }\n.rt-Card { border: 0; }\n"
    )
    (components / "button.css").write_text(".rt-Button { color: red; }")
    (components / "card.css").write_text(".rt-Card { border: 0; }")
    monkeypatch.setattr(prerequisites, "get_web_dir", lambda: web)

    plugin = RadixThemesPlugin(css_splitting=True)
    plugin.enabled = True
    assets = {path.as_posix(): content for path, content in plugin.get_static_assets()}

    assert "styles/radix/_shared.css" in assets
    assert "--x: 1;" in assets["styles/radix/_shared.css"]
    # Button/Card are loaded component classes, so their chunks are emitted.
    assert ".rt-Button { color: red; }" in assets["styles/radix/button.css"]
    assert ".rt-Card { border: 0; }" not in assets["styles/radix/button.css"]


def test_plugin_no_static_assets_without_splitting():
    """With splitting off, the plugin emits no chunks (full bundle is used)."""
    from reflex_components_radix.plugin import RadixThemesPlugin

    plugin = RadixThemesPlugin(css_splitting=False)
    plugin.enabled = True
    assert plugin.get_static_assets() == []
