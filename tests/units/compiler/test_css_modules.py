"""Tests for per-component CSS module compilation and tree-shaking."""

from pathlib import Path

from reflex_base.components.css_module import CSSModuleComponent

import reflex as rx
from reflex.compiler import compiler
from reflex.compiler import utils as compiler_utils

FIXTURES = Path(__file__).parent / "fixtures" / "css_modules"
BUTTON_CSS = FIXTURES / "button.module.css"
ATOMS_CSS = FIXTURES / "_atoms.module.css"


class StyledBox(CSSModuleComponent):
    """A throwaway component styled by a co-located CSS module."""

    tag = "div"
    _css_module = str(BUTTON_CSS)
    _css_module_shared = (str(ATOMS_CSS),)


def test_descriptor_resolves_paths_and_binding():
    """The descriptor resolves the source, web destination, lib and binding."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    assert descriptor.source_path == BUTTON_CSS.resolve()
    assert descriptor.dest_relpath.startswith("styles/components/")
    assert descriptor.dest_relpath.endswith("/button.module.css")
    assert descriptor.lib == f"$/{descriptor.dest_relpath}"
    assert descriptor.binding.startswith("_rxcss_")
    assert descriptor.shared == (
        (ATOMS_CSS.resolve(), "styles/_shared/_atoms.module.css"),
    )


def test_class_name_references_module_binding():
    """The component applies ``<binding>.root`` as its className."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    comp = StyledBox.create()
    assert str(comp.class_name) == f"{descriptor.binding}.root"


def test_user_class_name_is_preserved_alongside_module():
    """A user-supplied class_name is joined with the module class."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    comp = StyledBox.create(class_name="extra")
    rendered = str(comp.class_name)
    assert descriptor.binding in rendered
    assert "extra" in rendered


def test_mounted_component_emits_default_import():
    """A mounted component emits ``import <binding> from "<lib>"``."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    comp = StyledBox.create()
    all_imports = comp._get_all_imports()
    assert descriptor.lib in all_imports

    compiled = compiler_utils.compile_imports(all_imports)
    css_import = next(imp for imp in compiled if imp["lib"] == descriptor.lib)
    assert css_import["default"] == descriptor.binding
    assert css_import["rest"] == []


def test_mounted_component_collects_assets():
    """The mounted component's module and shared atoms are collected once."""
    tree = rx.box(rx.text("hi"), StyledBox.create())
    assets = {dest: src for src, dest in tree._get_all_css_module_assets()}
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    assert assets[descriptor.dest_relpath] == BUTTON_CSS.resolve()
    assert assets["styles/_shared/_atoms.module.css"] == ATOMS_CSS.resolve()


def test_unused_component_ships_zero_css():
    """A tree without the component emits no css imports and no assets."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    tree = rx.box(rx.text("nothing styled here"))
    assert tree._get_all_css_module_assets() == []
    assert descriptor.lib not in tree._get_all_imports()


def test_compile_css_modules_writes_contents_and_dedupes():
    """The compiler pass returns ``(dest, contents)`` and dedupes shared atoms."""
    descriptor = StyledBox._css_module_descriptor()
    assert descriptor is not None
    # Two instances of the same component in the tree.
    tree = rx.box(StyledBox.create(), StyledBox.create())
    results = dict(compiler.compile_css_modules([tree]))

    assert results[descriptor.dest_relpath] == BUTTON_CSS.read_text()
    # Shared atoms collapse to a single entry despite two instances.
    assert results["styles/_shared/_atoms.module.css"] == ATOMS_CSS.read_text()
    assert len(results) == 2


def test_compile_css_modules_empty_when_unused():
    """The compiler pass emits nothing for a tree without CSS modules."""
    tree = rx.box(rx.text("plain"))
    assert compiler.compile_css_modules([tree]) == []
