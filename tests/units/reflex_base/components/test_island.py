"""Unit tests for the rx.island(...) compile-time API.

Covers `packages/reflex-base/src/reflex_base/components/island.py`.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from reflex_base.components.island import (
    IslandComponent,
    IslandSpec,
    _validate_hydrate,
    island,
)
from reflex_base.utils.exceptions import CompileError


def _stub_component():
    """Return a minimal duck-typed component for unit-testing the wrapper.

    The :func:`island` factory only stores the wrapped value as-is and
    forwards `.render(...)` to it; we don't need a real Component here.
    """
    return SimpleNamespace(render=lambda *a, **kw: ("rendered", a, kw))


def test_island_default_spec():
    """`hydrate` defaults to "load" and `client_only` defaults to False."""
    comp = _stub_component()
    wrapper = island(comp)  # pyright: ignore[reportArgumentType]
    assert isinstance(wrapper, IslandComponent)
    assert isinstance(wrapper.spec, IslandSpec)
    assert wrapper.spec.hydrate == "load"
    assert wrapper.spec.client_only is False
    assert wrapper.component is comp


@pytest.mark.parametrize("strategy", ["load", "idle", "visible"])
def test_island_accepts_each_strategy(strategy: str):
    """All three strategy strings round-trip into the spec."""
    wrapper = island(_stub_component(), hydrate=strategy)  # pyright: ignore[reportArgumentType]
    assert wrapper.spec.hydrate == strategy


def test_island_accepts_media_mapping():
    """A `{"media": "..."}` mapping is stored as-is on the spec."""
    media = {"media": "(max-width: 768px)"}
    wrapper = island(_stub_component(), hydrate=media)  # pyright: ignore[reportArgumentType]
    assert wrapper.spec.hydrate == media


def test_island_rejects_bad_strategy():
    """Unknown strategy strings raise CompileError."""
    with pytest.raises(CompileError, match=r"Invalid hydrate"):
        island(_stub_component(), hydrate="never")  # pyright: ignore[reportArgumentType]


def test_island_rejects_bad_media_mapping():
    """A media mapping with extra keys raises CompileError."""
    bad_media = {"media": "x", "extra": "y"}
    with pytest.raises(CompileError, match=r"media mapping"):
        island(_stub_component(), hydrate=bad_media)  # pyright: ignore[reportArgumentType]


def test_island_rejects_non_string_media():
    """A media mapping with a non-string value raises CompileError."""
    with pytest.raises(CompileError, match=r"media mapping"):
        island(_stub_component(), hydrate={"media": 12})  # pyright: ignore[reportArgumentType]


def test_island_client_only_flag():
    """client_only=True propagates to the spec."""
    wrapper = island(_stub_component(), client_only=True)  # pyright: ignore[reportArgumentType]
    assert wrapper.spec.client_only is True


def test_island_client_only_truthy_normalized_to_bool():
    """client_only is normalized via bool() so non-bool truthy values still work."""
    wrapper = island(_stub_component(), client_only=1)  # pyright: ignore[reportArgumentType]
    assert wrapper.spec.client_only is True


def test_island_rejects_nested_island():
    """Wrapping an already-wrapped IslandComponent is a CompileError (v1)."""
    inner = island(_stub_component())  # pyright: ignore[reportArgumentType]
    with pytest.raises(CompileError, match=r"Nested rx\.island"):
        island(inner)  # pyright: ignore[reportArgumentType]


def test_island_render_delegates_to_inner():
    """The wrapper forwards .render() to the inner component."""
    comp = _stub_component()
    wrapper = island(comp)  # pyright: ignore[reportArgumentType]
    result = wrapper.render("a", k=1)
    assert result == ("rendered", ("a",), {"k": 1})


def test_validate_hydrate_returns_normalized_value():
    """_validate_hydrate returns a fresh dict for media mappings."""
    media = {"media": "(prefers-color-scheme: dark)"}
    out = _validate_hydrate(media)
    assert out == media


def test_validate_hydrate_rejects_arbitrary_object():
    """Non-string, non-mapping values raise CompileError."""
    with pytest.raises(CompileError):
        _validate_hydrate(12)
    with pytest.raises(CompileError):
        _validate_hydrate(None)


def test_island_spec_is_frozen():
    """IslandSpec is frozen; attributes cannot be reassigned."""
    spec = IslandSpec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.hydrate = "idle"  # pyright: ignore[reportAttributeAccessIssue]
