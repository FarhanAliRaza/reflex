"""TDD red-stage tests for the next arena-pipeline ports.

The post-`b7fc5898` profile shows the remaining wall-clock outside the
page+memo arena entry lives in three Python-driven blocks of
``rust_pipeline.py``:

1. ``compile_app_root_module`` is fed a hand-built string for every
   slot (``imports_str``, ``custom_code_str``, ``hooks_str``,
   ``render_str``, ``dynamic_imports_str``). Each string requires
   running a recursive Python walk over the ``app_root`` Component
   tree. **Movable**: the arena freeze already does these harvests in
   one PyO3 pass.
2. ``compile_document_root_module`` is fed a pre-rendered import
   block + JSX string built from a Python ``create_document_root``
   call. **Movable**: same shape as app_root, just smaller.
3. ``compile_theme_module`` takes ``theme_js = str(LiteralVar.create(
   theme_component))`` — a Python serialization of the resolved theme
   Component. **Movable**: freeze the theme component and emit JS
   directly.

Per-memo file emission was a fourth block, but the legacy
``CUSTOM_COMPONENTS`` registry it relied on was removed when ``main``
unified ``@rx.memo`` into ``reflex_base.components.memo.MEMOS``; that
emission is dropped here pending a rewrite against the new registry.

For each feature there are three classes of test:

* ``test_*_exists`` — the new ``CompilerSession`` method is present.
* ``test_*_matches_legacy`` — the new method's output is byte-equivalent
  to the current Python+Rust chain.
* ``test_rust_pipeline_uses_*`` — ``reflex/compiler/rust_pipeline.py``
  actually calls the new method (not the old Python harvest chain).
* ``test_*_legacy_chain_removed`` — the old Python harvest pattern is
  gone from ``rust_pipeline.py`` (string-input ``compile_*_module``
  signatures, ``create_document_root``, ``LiteralVar.create(theme)``,
  ``_compile_memo_components``, etc.).

Today every test in this file fails. Once the new methods land AND
``rust_pipeline.py`` is rewired to call them AND the old chains are
deleted, every test goes green.

Run with::

    uv run pytest tests/units/compiler/test_arena_followup.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("reflex_base")
pytest.importorskip("reflex_components_core")
pytest.importorskip("reflex_compiler_rust._native")


import reflex as rx
from reflex.compiler.session import CompilerSession


REPO = Path(__file__).resolve().parents[3]
RUST_PIPELINE_PATH = REPO / "reflex/compiler/rust_pipeline.py"


@pytest.fixture(scope="module")
def sess() -> CompilerSession:
    return CompilerSession()


@pytest.fixture(scope="module")
def rust_pipeline_source() -> str:
    return RUST_PIPELINE_PATH.read_text()


class _FollowupState(rx.State):
    title: str = "Followup"
    count: int = 0

    def increment(self) -> None:
        self.count += 1


def _toy_app_root() -> Any:
    """Build a small app_root-shaped Component tree.

    Matches the structural shape of ``app._app_root(...)``: a top-level
    container plus a child stack. Enough surface for the harvest passes
    (imports, hooks, custom code, dynamic imports, render) to have real
    output to compare.
    """
    return rx.fragment(
        rx.container(
            rx.heading(_FollowupState.title, size="6"),
            rx.text("Count: ", _FollowupState.count.to_string()),
            rx.button("Inc", on_click=_FollowupState.increment),
        ),
    )


def _toy_document_head() -> list[Any]:
    return [
        rx.el.meta(name="description", content="Followup test app"),
        rx.el.link(rel="icon", href="/favicon.ico"),
    ]


# ---------------------------------------------------------------------------
# 1. App root via arena
# ---------------------------------------------------------------------------


def test_compile_app_root_arena_exists(sess: CompilerSession) -> None:
    """RED: ``compile_app_root_arena`` does not exist yet.

    Contract: a new single-call PyO3 entry that takes the app_root
    Component plus the still-Python-side bundled-library strings
    (``import_window_libraries``, ``window_imports``) and returns
    ``(root_jsx_was_written: bool, imports_dict: dict[str, list])``.

    Internally freezes ``app_root``, runs ``harvest::*`` for imports
    / custom_code / hooks / dynamic_imports, emits the React Router
    root template, writes via ``write_if_changed``.
    """
    assert hasattr(sess, "compile_app_root_arena"), (
        "CompilerSession needs `compile_app_root_arena(component, "
        "import_window_libraries, window_imports, out_path)` so "
        "rust_pipeline.py:316-344 stops doing per-page Python walks "
        "for imports/custom_code/hooks/render/dynamic_imports."
    )


def test_compile_app_root_arena_matches_legacy(
    sess: CompilerSession, tmp_path: Path
) -> None:
    """GREEN once implemented: arena emit must embed every JS payload
    the legacy Python harvest chain produced.

    We can no longer call the old ``compile_app_root_module`` to build
    a parallel baseline (it's removed), so the contract becomes
    "arena output contains all the strings the legacy chain would have
    embedded." Specifically the rendered JSX, every harvested hook,
    and every harvested import line.
    """
    if not hasattr(sess, "compile_app_root_arena"):
        pytest.fail(
            "compile_app_root_arena not implemented — see "
            "test_compile_app_root_arena_exists for the contract."
        )

    from reflex.compiler import utils as compiler_utils
    from reflex.compiler.compiler import _apply_common_imports
    from reflex_base.compiler.templates import _RenderUtils, _render_hooks

    app_root = _toy_app_root()
    app_root_imports = app_root._get_all_imports()
    _apply_common_imports(app_root_imports)
    expected_imports_lines = [
        _RenderUtils.get_import(m)
        for m in compiler_utils.compile_imports(app_root_imports)
    ]
    expected_render = _RenderUtils.render(app_root.render())
    expected_hooks = _render_hooks(app_root._get_all_hooks())

    arena_out = tmp_path / "arena_root.jsx"
    arena_imports = sess.compile_app_root_arena(
        app_root,
        import_window_libraries="",
        window_imports="",
        out_path=str(arena_out),
    )
    written = arena_out.read_text()

    assert expected_render in written, (
        "arena app_root output must embed the rendered JSX produced by "
        "_RenderUtils.render(app_root.render())"
    )
    if expected_hooks.strip():
        assert expected_hooks.strip() in written, (
            "arena app_root output must embed the rendered hooks body"
        )
    for line in expected_imports_lines:
        assert line.strip() in written, (
            f"arena app_root output is missing legacy import line: {line!r}"
        )
    # Bun-install imports dict must include every library the legacy
    # `_get_all_imports` walk would have surfaced.
    assert set(arena_imports.keys()) >= set(app_root._get_all_imports().keys())


# ---------------------------------------------------------------------------
# 2. Document root via arena
# ---------------------------------------------------------------------------


def test_compile_document_root_arena_exists(sess: CompilerSession) -> None:
    """RED: ``compile_document_root_arena`` does not exist yet.

    Contract: takes the user's ``head_components`` list (plus
    ``html_lang`` and ``html_custom_attrs``) directly, internally
    builds the document_root Component tree via the same helper the
    legacy chain uses, freezes it, harvests imports, emits.
    """
    assert hasattr(sess, "compile_document_root_arena"), (
        "CompilerSession needs `compile_document_root_arena("
        "head_components, html_lang, html_custom_attrs, out_path)` "
        "so rust_pipeline.py:438-458 stops calling "
        "create_document_root + _RenderUtils.render in Python."
    )


def test_compile_document_root_arena_matches_legacy(
    sess: CompilerSession, tmp_path: Path
) -> None:
    """GREEN once implemented: arena emit must embed every JS payload
    the legacy ``create_document_root`` chain produced.

    The old ``compile_document_root_module`` PyO3 entry is removed
    (see ``test_native_compile_document_root_module_string_input_removed``)
    so the parallel baseline becomes "compute what the chain WOULD
    have rendered with primitives that still exist."
    """
    if not hasattr(sess, "compile_document_root_arena"):
        pytest.fail(
            "compile_document_root_arena not implemented — see "
            "test_compile_document_root_arena_exists for the contract."
        )

    from reflex.compiler import compiler as legacy_compiler
    from reflex.compiler import utils as legacy_utils
    from reflex_base.compiler.templates import _RenderUtils

    document_root = legacy_utils.create_document_root(
        _toy_document_head(),
        html_lang="en",
        html_custom_attrs={"suppressHydrationWarning": True},
    )
    doc_imports = document_root._get_all_imports()
    legacy_compiler._apply_common_imports(doc_imports)
    expected_imports_lines = [
        _RenderUtils.get_import(m)
        for m in legacy_utils.compile_imports(doc_imports)
    ]
    expected_render = _RenderUtils.render(document_root.render())

    arena_out = tmp_path / "arena_doc.js"
    sess.compile_document_root_arena(
        head_components=_toy_document_head(),
        html_lang="en",
        html_custom_attrs={"suppressHydrationWarning": True},
        out_path=str(arena_out),
    )
    written = arena_out.read_text()

    assert expected_render in written, (
        "arena _document.js must embed the rendered JSX produced by "
        "_RenderUtils.render(document_root.render())"
    )
    for line in expected_imports_lines:
        assert line.strip() in written, (
            f"arena _document.js is missing legacy import line: {line!r}"
        )


# ---------------------------------------------------------------------------
# 3. Theme module from Component
# ---------------------------------------------------------------------------


def test_compile_theme_from_component_arena_exists(sess: CompilerSession) -> None:
    """RED: ``compile_theme_from_component_arena`` does not exist yet.

    Contract: takes a theme Component instance directly and emits
    ``utils/theme.js`` via the arena pipeline. Replaces the current
    ``theme_js = str(LiteralVar.create(theme_component))`` shuttle.
    """
    assert hasattr(sess, "compile_theme_from_component_arena"), (
        "CompilerSession needs `compile_theme_from_component_arena("
        "theme_component, out_path)` so rust_pipeline.py:486-490 "
        "stops calling LiteralVar.create + str() to render the theme."
    )


def test_compile_theme_from_component_arena_matches_legacy(
    sess: CompilerSession, tmp_path: Path
) -> None:
    """GREEN once implemented: output must embed the same JS payload
    ``str(LiteralVar.create(theme_component))`` would produce.

    We can no longer call the old ``compile_theme_module`` to build a
    parallel baseline because it's removed (see
    ``test_native_compile_theme_module_string_input_removed``), so the
    contract becomes "arena output contains the LiteralVar-rendered
    payload."
    """
    if not hasattr(sess, "compile_theme_from_component_arena"):
        pytest.fail(
            "compile_theme_from_component_arena not implemented — "
            "see test_compile_theme_from_component_arena_exists."
        )

    from reflex.compiler import utils as legacy_utils
    from reflex_base.vars.base import LiteralVar

    theme_component = legacy_utils.create_theme({})
    expected_payload = str(LiteralVar.create(theme_component))

    out_path = tmp_path / "theme.js"
    sess.compile_theme_from_component_arena(theme_component, str(out_path))
    written = out_path.read_text()

    assert expected_payload in written, (
        "compile_theme_from_component_arena output must embed the "
        f"LiteralVar-rendered JS payload"
    )
    assert "export default" in written, (
        "theme.js must declare a default export"
    )


# ---------------------------------------------------------------------------
# Usage + removal — rust_pipeline.py must call the new methods AND drop
# the per-page Python harvest chains. These tests are the structural
# half of red/green: a method existing is necessary but not sufficient,
# the pipeline must actually adopt it.
# ---------------------------------------------------------------------------


def test_rust_pipeline_uses_compile_app_root_arena(
    rust_pipeline_source: str,
) -> None:
    """``rust_pipeline.py`` must call ``sess.compile_app_root_arena``.

    The current code at lines 308-344 hand-builds five strings via
    Python tree walks and passes them into ``compile_app_root_module``.
    After the cutover, that whole block becomes a single
    ``sess.compile_app_root_arena(app_root, ...)`` call.
    """
    assert "compile_app_root_arena" in rust_pipeline_source, (
        "rust_pipeline.py must call sess.compile_app_root_arena(...) "
        "instead of the imports_str / custom_code_str / hooks_str / "
        "render_str / dynamic_imports_str chain feeding "
        "compile_app_root_module."
    )


def test_app_root_legacy_chain_removed(rust_pipeline_source: str) -> None:
    """The old Python harvest chain feeding ``compile_app_root_module``
    is gone from ``rust_pipeline.py``."""
    forbidden = [
        "app_root._get_all_imports()",
        "app_root._get_all_custom_code()",
        "app_root._get_all_hooks()",
        "app_root._get_all_dynamic_imports()",
        "_RenderUtils.render(app_root.render())",
        # The string-fed PyO3 entry should not be called from this
        # module anymore. compile_app_root_arena replaces it.
        "sess.compile_app_root_module(",
    ]
    found = [token for token in forbidden if token in rust_pipeline_source]
    assert not found, (
        f"rust_pipeline.py still contains pre-arena app_root harvest "
        f"calls: {found}. Move them into compile_app_root_arena."
    )


def test_native_compile_app_root_module_string_input_removed() -> None:
    """The PyO3 string-input ``compile_app_root_module`` is gone.

    The arena entry takes the Component directly, so the seven-string
    signature on the native session is dead surface area after the
    cutover.
    """
    from reflex.compiler.session import CompilerSession

    sess = CompilerSession()
    assert not hasattr(sess, "compile_app_root_module"), (
        "compile_app_root_module(imports_str, dynamic_imports_str, ...) "
        "must be removed from CompilerSession after "
        "compile_app_root_arena lands — its only caller was the "
        "Python harvest chain in rust_pipeline.py."
    )


def test_rust_pipeline_uses_compile_document_root_arena(
    rust_pipeline_source: str,
) -> None:
    """``rust_pipeline.py`` must call ``compile_document_root_arena``
    instead of running ``create_document_root`` + ``compile_imports``
    + ``_RenderUtils.render`` in Python."""
    assert "compile_document_root_arena" in rust_pipeline_source, (
        "rust_pipeline.py must call "
        "sess.compile_document_root_arena(head_components, ...) "
        "instead of the legacy create_document_root chain."
    )


def test_document_root_legacy_chain_removed(rust_pipeline_source: str) -> None:
    """The legacy ``create_document_root`` + string-feed pattern is
    gone from ``rust_pipeline.py``."""
    forbidden = [
        "create_document_root(",
        "document_root._get_all_imports()",
        "_RenderUtils.render(document_root.render())",
        "sess.compile_document_root_module(",
    ]
    found = [token for token in forbidden if token in rust_pipeline_source]
    assert not found, (
        f"rust_pipeline.py still contains pre-arena document_root "
        f"chain calls: {found}. Move them into "
        f"compile_document_root_arena."
    )


def test_native_compile_document_root_module_string_input_removed() -> None:
    """The string-input ``compile_document_root_module`` PyO3 entry
    must be retired once ``compile_document_root_arena`` exists."""
    from reflex.compiler.session import CompilerSession

    sess = CompilerSession()
    assert not hasattr(sess, "compile_document_root_module"), (
        "compile_document_root_module(imports_str, render_str, "
        "out_path) must be removed from CompilerSession — its only "
        "caller was the Python create_document_root chain."
    )


def test_rust_pipeline_uses_compile_theme_from_component_arena(
    rust_pipeline_source: str,
) -> None:
    """``rust_pipeline.py`` must call
    ``sess.compile_theme_from_component_arena`` so the theme
    Component flows straight into the emit without a
    ``LiteralVar.create + str()`` round-trip."""
    assert (
        "compile_theme_from_component_arena" in rust_pipeline_source
    ), (
        "rust_pipeline.py must call "
        "sess.compile_theme_from_component_arena(theme_component, "
        "out_path) instead of LiteralVar.create + "
        "compile_theme_module(theme_js, ...)."
    )


def test_theme_legacy_chain_removed(rust_pipeline_source: str) -> None:
    """The ``LiteralVar.create(theme_component)`` + string-feed pattern
    must be gone from ``rust_pipeline.py``."""
    forbidden = [
        "LiteralVar.create(theme_component)",
        "str(LiteralVar.create(theme_component))",
        "sess.compile_theme_module(",
    ]
    found = [token for token in forbidden if token in rust_pipeline_source]
    assert not found, (
        f"rust_pipeline.py still contains pre-arena theme chain "
        f"calls: {found}. Move them into "
        f"compile_theme_from_component_arena."
    )


def test_native_compile_theme_module_string_input_removed() -> None:
    """The string-input ``compile_theme_module`` PyO3 entry should be
    retired once the Component-input variant ships."""
    from reflex.compiler.session import CompilerSession

    sess = CompilerSession()
    assert not hasattr(sess, "compile_theme_module"), (
        "compile_theme_module(theme_js, out_path) must be removed "
        "from CompilerSession — its only caller was the "
        "LiteralVar.create(theme_component) chain."
    )


def test_legacy_compiler_import_removed(rust_pipeline_source: str) -> None:
    """After every static-artifact + custom-component port lands,
    ``rust_pipeline.py`` no longer needs ``legacy_compiler``: every
    callee on it was a thin wrapper around the legacy plugin chain.
    """
    forbidden_imports = [
        "from reflex.compiler import compiler as legacy_compiler",
        "import reflex.compiler.compiler as legacy_compiler",
    ]
    found = [token for token in forbidden_imports if token in rust_pipeline_source]
    assert not found, (
        f"rust_pipeline.py still imports legacy_compiler: {found}. "
        f"Every callee on it should be replaced by a CompilerSession "
        f"arena method."
    )


def test_arena_end_to_end_no_legacy_calls(tmp_path: Path) -> None:
    """End-to-end: after all four ports land, ``compile_pages`` runs
    without any of the deleted Python harvest functions ever being
    invoked.

    Uses ``unittest.mock`` patches to make every legacy harvest raise
    if called. If the pipeline still touches one, the patched function
    fires and the test fails with a clear traceback.
    """
    from unittest.mock import patch

    # Build a tiny app the pipeline can compile.
    import reflex as rx
    from reflex.compiler import rust_pipeline

    def _index() -> rx.Component:
        return rx.text("hi", id="hello")

    app = rx.App()
    app.add_page(_index, route="/")

    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError(
            "legacy harvest path was called from the arena pipeline"
        )

    patches = [
        # The four harvests the arena entry must replace. These live on
        # `Component`, not on the abstract `BaseComponent` parent — the
        # latter has stub bodies that never get called via MRO. The
        # arena port must NOT invoke any of these on the app_root or
        # page Component trees; if any fires, the Python harvest is
        # still happening somewhere on the critical path.
        patch(
            "reflex_base.components.component.Component._get_all_imports",
            _explode,
        ),
        patch(
            "reflex_base.components.component.Component._get_all_custom_code",
            _explode,
        ),
        patch(
            "reflex_base.components.component.Component._get_all_hooks",
            _explode,
        ),
        patch(
            "reflex_base.components.component.Component._get_all_dynamic_imports",
            _explode,
        ),
        # The legacy plugin-chain callees that the ports replace.
        # ``_compile_memo_components`` stays guarded: the pipeline no
        # longer emits memos at all (the ``CUSTOM_COMPONENTS`` port was
        # dropped), so the legacy memo compiler must never fire here.
        patch("reflex.compiler.utils.create_document_root", _explode),
        patch("reflex.compiler.compiler._compile_memo_components", _explode),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        # If any patched function fires, rust_pipeline.compile_pages
        # raises AssertionError and the test reports which path got
        # called.
        rust_pipeline.compile_pages(app)
