"""Generic arena fast paths that avoid Python tree work."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

import pytest
from reflex_base.components.component import Component

from reflex.compiler.session import CompilerSession

pytest.importorskip("reflex_compiler_rust._native")


class _DefaultImportComponent(Component):
    tag = "DefaultImportComponent"
    library = "default-import-lib"


class _AddedImportComponent(Component):
    tag = "AddedImportComponent"
    library = "default-import-lib"

    def add_imports(self):
        """Return a custom import so the generic fast path must not apply."""
        return {"added-import-lib": "AddedThing"}


class _StaticAppWrapComponent(Component):
    tag = "StaticAppWrapComponent"
    library = "static-wrap-lib"
    wrap_factory_calls: ClassVar[int] = 0

    @staticmethod
    def _get_app_wrap_components() -> dict[tuple[int, str], Component]:
        """Return an app wrapper if a caller explicitly asks for it."""
        _StaticAppWrapComponent.wrap_factory_calls += 1
        return {(25, "ProofWrap"): _DefaultImportComponent.create()}


def _count_base_get_imports(component: Component) -> tuple[int, dict[str, list]]:
    original = Component._get_imports
    calls = 0

    def wrapped(self):
        nonlocal calls
        calls += 1
        return original(self)

    with patch.object(Component, "_get_imports", wrapped):
        _, _, imports, *_ = CompilerSession().compile_page_from_component_arena(
            component, "Index", "/"
        )
    return calls, imports


def test_default_trivial_components_skip_get_imports() -> None:
    """Default components can synthesize their import dict without Python."""
    component = _DefaultImportComponent.create(
        *(_DefaultImportComponent.create() for _ in range(5))
    )

    calls, imports = _count_base_get_imports(component)

    assert calls == 0
    assert "default-import-lib" in imports


def test_nontrivial_default_component_falls_back_to_get_imports() -> None:
    """Attrs like ``id`` can create hooks/vars, so they use the full path."""
    component = _DefaultImportComponent.create(id="needs_ref")

    calls, imports = _count_base_get_imports(component)

    assert calls == 1
    assert "default-import-lib" in imports
    assert "react" in imports


def test_component_with_custom_add_imports_falls_back_to_get_imports() -> None:
    """Component-level import overrides still run through Python."""
    component = _AddedImportComponent.create()

    calls, imports = _count_base_get_imports(component)

    assert calls == 1
    assert "added-import-lib" in imports


def test_arena_invokes_static_app_wrap_factory_once_per_class() -> None:
    """The freeze walk harvests app wraps inline — the factory runs once
    per class per session, never once per node or per page.
    """
    _StaticAppWrapComponent.wrap_factory_calls = 0
    sess = CompilerSession()

    page = Component.create(
        _StaticAppWrapComponent.create(),
        _StaticAppWrapComponent.create(),
        _StaticAppWrapComponent.create(),
    )
    _, _, _, wraps = sess.compile_page_from_component_arena(page, "Index", "/")

    assert _StaticAppWrapComponent.wrap_factory_calls == 1
    assert list(wraps) == [(25, "ProofWrap")]
    assert type(wraps[25, "ProofWrap"]) is _DefaultImportComponent

    # Second page on the same session hits the per-class dict cache.
    _, _, _, wraps2 = sess.compile_page_from_component_arena(
        Component.create(_StaticAppWrapComponent.create()), "Index2", "/two"
    )
    assert _StaticAppWrapComponent.wrap_factory_calls == 1
    assert list(wraps2) == [(25, "ProofWrap")]
