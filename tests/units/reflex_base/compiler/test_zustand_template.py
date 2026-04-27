"""Unit tests for the Zustand store + event-loop runtime templates.

Covers ``packages/reflex-base/src/reflex_base/compiler/zustand_template.py``.
The templates are pure-string codegen, so the assertions verify the
generated JS contains the right exports, hook names, and atomic update
shape (one ``set`` call per ``applyDelta``).
"""

from __future__ import annotations

from reflex_base.compiler.zustand_template import (
    color_mode_inline_setter_template,
    event_loop_runtime_template,
    zustand_store_template,
)


def test_zustand_store_template_imports_zustand():
    src = zustand_store_template()
    assert 'from "zustand"' in src or "from 'zustand'" in src
    assert "create" in src


def test_zustand_store_template_exposes_each_slice():
    src = zustand_store_template()
    for slice_name in ("state", "dispatch", "eventLoop", "uploads", "colorMode"):
        assert slice_name in src


def test_zustand_store_template_exposes_each_hook():
    src = zustand_store_template()
    for hook in (
        "useReflexStore",
        "useReflexState",
        "useReflexDispatch",
        "useReflexEventLoop",
        "useReflexUploads",
        "useReflexColorMode",
    ):
        assert f"export const {hook}" in src or f"export const {hook} =" in src


def test_zustand_store_template_atomic_apply_delta():
    """The applyDelta action must do exactly one set() call per delta."""
    src = zustand_store_template()
    # The applyDelta entry uses a single `set((prev) => ...)` — one set call,
    # one return — so subscribers see one commit per backend delta.
    apply_delta_section = src.split("applyDelta:")[1].split("setStateSlice")[0]
    assert apply_delta_section.count("set(") == 1


def test_zustand_store_template_imperative_accessors():
    src = zustand_store_template()
    for accessor in (
        "getReflexState",
        "getReflexDispatch",
        "applyReflexDelta",
        "setReflexEventLoop",
        "setReflexColorMode",
        "registerReflexDispatch",
        "getReflexDispatches",
    ):
        assert f"export const {accessor}" in src


def test_zustand_store_template_upload_updater_action():
    src = zustand_store_template()
    assert "setUploadsByUpdater" in src


def test_zustand_store_template_hooks_fallback_to_current_snapshot():
    """SSR hook reads must see state seeded after store creation."""
    src = zustand_store_template()
    assert "useReflexStore.getState().state[stateName]" in src
    assert "useReflexStore.getState().dispatch[stateName]" in src
    assert "useReflexStore.getState().uploads[componentId]" in src


def test_event_loop_runtime_template_imports_store():
    src = event_loop_runtime_template()
    assert "$/utils/store" in src
    assert "applyReflexDelta" in src
    assert "setReflexEventLoop" in src


def test_event_loop_runtime_template_exposes_set_adapter():
    src = event_loop_runtime_template()
    assert "setEventLoopAdapter" in src
    assert "getEventLoopAdapter" in src
    assert "dispatchEventChain" in src


def test_event_loop_runtime_template_no_react_import():
    """The runtime module is target-agnostic — it must not pull in React or React Router."""
    src = event_loop_runtime_template()
    assert 'from "react"' not in src
    assert "from 'react'" not in src
    assert "react-router" not in src


def test_color_mode_inline_setter_template_returns_function():
    src = color_mode_inline_setter_template()
    assert "export const colorModeInlineScript" in src
    assert "prefers-color-scheme: dark" in src
    assert "data-color-mode" in src


def test_color_mode_inline_setter_template_no_imports():
    """Inline head script must be self-contained — no module imports."""
    src = color_mode_inline_setter_template()
    assert "import " not in src


def test_zustand_store_color_mode_setters_are_not_noop():
    """``initialColorMode.setColorMode`` must apply the change in-store.

    Regression: with the React Router target the
    ``RadixThemesColorModeProvider`` mounts at app-root and pushes real
    setters into the store on hydration. The Astro islands target has no
    app-root, so without these defaults the click handler ends up calling
    ``noop`` and theme switching silently does nothing.
    """
    src = zustand_store_template()
    # The slice's setters are the ones returned by ``useReflexColorMode()``
    # — they must wire through to the real DOM/cookie/storage commit path.
    assert "setColorMode: noop" not in src
    assert "toggleColorMode: noop" not in src
    assert "_commitColorMode" in src


def test_zustand_store_color_mode_persists_to_cookie_and_storage():
    """Setting the color mode persists to cookie + localStorage."""
    src = zustand_store_template()
    assert "reflex-color-mode" in src
    assert "color_mode" in src
    # Cookie write path must set max-age so the choice survives reloads.
    assert "max-age=" in src
    # localStorage write path must guard against private mode / no-storage.
    assert "localStorage.setItem" in src


def test_zustand_store_color_mode_applies_class_to_root():
    """Changes update ``<html>``'s class so dark/light CSS rules switch."""
    src = zustand_store_template()
    assert 'classList.remove("light", "dark")' in src
    assert "documentElement" in src
    # Hint the UA so native form controls also pick the right palette.
    assert "colorScheme" in src


def test_zustand_store_color_mode_resolves_system_preference():
    """``system`` mode must resolve via ``matchMedia`` not just pass through."""
    src = zustand_store_template()
    assert 'matchMedia("(prefers-color-scheme: dark)")' in src
    # And it must keep listening so OS-level changes propagate while the
    # user is on ``system`` mode.
    assert 'addEventListener("change"' in src


def test_zustand_store_event_loop_handles_call_function_locally():
    """``addEvents`` must handle ``_call_function`` without a backend adapter.

    Regression: islands-mode pages don't mount the React Router event loop
    so ``addEvents`` was ``noop``. Every ``on_click=set_color_mode(...)`` /
    ``on_click=rx.call_script(...)`` button silently dropped its handler.
    The store now ships a local handler that runs ``_call_function`` and
    ``_call_script`` events directly so front-end-only events work without
    state.js wiring up a real adapter.
    """
    src = zustand_store_template()
    assert "addEvents: _localAddEvents" in src
    assert "_runLocalEvent" in src
    assert '"_call_function"' in src
    assert '"_call_script"' in src


def test_zustand_store_event_loop_default_is_not_noop():
    """The eventLoop slice's addEvents must do real work, not noop."""
    src = zustand_store_template()
    assert "addEvents: noop" not in src


def test_zustand_store_color_mode_ssr_safe():
    """Module evaluates without ``window``/``document``.

    Astro SSRs every island server-side, where neither global exists. The
    color-mode wiring must guard each access so the module load doesn't
    throw during SSR.
    """
    src = zustand_store_template()
    assert 'typeof window !== "undefined"' in src
    assert 'typeof document !== "undefined"' in src
