"""Unit tests for ``reflex_base.compiler.templates.context_template``.

Focuses on the additions for the Astro migration:
- the Zustand store re-exports inserted at module top
- the Zustand-backed provider compatibility shell
- the ``omit_on_load_internal`` switch for islands-mode pages
"""

from __future__ import annotations

from reflex_base.compiler.templates import app_root_template, context_template


def test_context_template_imports_store_module():
    """The generated context.js imports from $/utils/store."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    assert "$/utils/store" in src


def test_context_template_state_contexts_default_to_empty_object():
    """Each StateContexts slice defaults to ``{}`` (not ``null``) for SSR safety.

    Auto-memo wrappers do ``useContext(StateContexts.foo).bar_rx_state_``
    during render. With a ``null`` default the SSR pass crashes
    immediately; with ``{}`` the access returns ``undefined`` and Reflex
    var rendering handles that gracefully.
    """
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "createContext({})" in src
    # The legacy null default should NOT appear for state contexts.
    assert "state: createContext(null)" not in src


def test_context_template_dispatch_event_loop_upload_have_ssr_defaults():
    """DispatchContext / EventLoopContext / UploadFilesContext default to safe shapes."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    # The defaults are object/array shapes that don't crash on common
    # access patterns (e.g. destructure, .foo lookups).
    assert "_ssrUploadDefault" in src
    assert "_ssrDispatchDefault" in src
    assert "_ssrEventLoopDefault" in src
    # And those are plugged in as the createContext defaults.
    assert "createContext(_ssrUploadDefault)" in src
    assert "createContext(_ssrDispatchDefault)" in src
    assert "createContext(_ssrEventLoopDefault)" in src


def test_context_template_re_exports_zustand_hooks():
    """Helper hooks are re-exported so existing call sites can migrate."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    for hook in (
        "useReflexState",
        "useReflexDispatch",
        "useReflexEventLoop",
        "useReflexUploads",
        "useReflexColorMode",
        "useReflexStore",
    ):
        assert hook in src


def test_context_template_mirrors_initial_state_into_store():
    """Module top must seed the Zustand store with initialState."""
    src = context_template(
        is_dev_mode=False,
        default_color_mode='"system"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "useReflexStore.getState().setStateSlice" in src


def test_context_template_event_loop_provider_mirrors_to_zustand():
    """EventLoopProvider must call _zustandSetEventLoop when the loop changes."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    assert "_zustandSetEventLoop" in src
    assert "EventLoopProvider" in src


def test_context_template_state_provider_uses_zustand_as_source_of_truth():
    """StateProvider reads slices from Zustand and dispatches deltas into it."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert 'const state = useReflexState("state")' in src
    assert "useReducer" not in src
    assert "applyDeltaWithMirror" not in src
    assert '"state": (delta) => _zustandApplyDelta({"state": delta})' in src
    assert "_zustandApplyDelta" in src


def test_context_template_state_provider_registers_dispatch():
    """The generated context module registers each store-backed dispatcher."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "_zustandRegisterDispatch" in src


def test_context_template_upload_provider_uses_store():
    """UploadFilesProvider reads and updates the upload slice in Zustand."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    assert "const filesById = useReflexStore((s) => s.uploads);" in src
    assert "const setFilesById = useReflexStore((s) => s.setUploadsByUpdater);" in src
    assert 'refs["__clear_selected_files"] = clearUploads;' in src


def test_context_template_omit_on_load_internal_default_includes_it():
    """Default behavior: initialEvents fires HYDRATE + onLoadInternalEvent()."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "onLoadInternalEvent()" in src


def test_context_template_omit_on_load_internal_skips_it():
    """Astro islands mode: initialEvents only fires HYDRATE."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
        omit_on_load_internal=True,
    )
    # The token "onLoadInternalEvent" still appears as a function declaration,
    # but the spread "...onLoadInternalEvent()" must NOT appear inside the
    # initialEvents body.
    assert "...onLoadInternalEvent()" not in src
    assert "HYDRATE" in src or "hydrate" in src


def test_app_root_template_astro_omits_document_and_react_router_imports():
    """Astro app roots provide runtime wrappers without nesting a document shell."""
    src = app_root_template(
        imports=[],
        custom_codes=[],
        hooks={},
        window_libraries=[],
        render={"name": "Fragment", "props": [], "children": ["children"]},
        dynamic_imports=set(),
        frontend_target="astro",
    )
    assert "./_document" not in src
    assert "react-router" not in src
    assert "export function Layout" in src
    assert "jsx(ThemeProvider" in src
