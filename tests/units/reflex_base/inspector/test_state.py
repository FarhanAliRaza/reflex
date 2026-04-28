"""Tests for the global enabled flag."""

from __future__ import annotations

from reflex_base.inspector import state


def test_default_disabled():
    # State is module-level, so reset to default before checking.
    state.set_enabled(False)
    assert state.is_enabled() is False


def test_set_enabled_round_trip():
    state.set_enabled(True)
    assert state.is_enabled() is True
    state.set_enabled(False)
    assert state.is_enabled() is False


def test_is_enabled_returns_bool():
    state.set_enabled(True)
    assert state.is_enabled() is True
    state.set_enabled(False)
    assert state.is_enabled() is False
