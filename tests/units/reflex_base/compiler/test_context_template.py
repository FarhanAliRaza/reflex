"""Unit tests for ``reflex_base.compiler.templates.context_template``.

Focuses on the additions for the Astro migration:
- the Zustand store re-exports inserted at module top
- the mirror-into-Zustand calls inside ``EventLoopProvider`` / ``StateProvider``
- the ``omit_on_load_internal`` switch for islands-mode pages
"""

from __future__ import annotations

from reflex_base.compiler.templates import context_template


def test_context_template_imports_store_module():
    """The generated context.js imports from $/utils/store."""
    src = context_template(is_dev_mode=True, default_color_mode='"light"')
    assert "$/utils/store" in src


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


def test_context_template_apply_delta_mirror():
    """The reducer wraps applyDelta to also call _zustandApplyDelta."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "applyDeltaWithMirror" in src
    assert "_zustandApplyDelta" in src


def test_context_template_state_provider_registers_dispatch():
    """StateProvider must call _zustandRegisterDispatch for each slice."""
    src = context_template(
        is_dev_mode=True,
        default_color_mode='"light"',
        state_name="state",
        initial_state={"state": {"foo": 1}},
    )
    assert "_zustandRegisterDispatch" in src


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
