"""Tests for source-map emission."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from reflex_base.inspector import capture, emit, state


@pytest.fixture
def enabled_inspector():
    capture.reset()
    state.set_enabled(True)
    yield
    state.set_enabled(False)
    capture.reset()


def test_write_source_map_skipped_when_disabled(tmp_path: Path):
    capture.reset()
    state.set_enabled(False)
    capture._REGISTRY[42] = capture.SourceInfo(
        file="/tmp/x.py", line=1, column=1, component="X"
    )
    assert emit.write_source_map(tmp_path) is None
    assert not (tmp_path / emit.SOURCE_MAP_DIRNAME).exists()


def test_write_source_map_round_trip(enabled_inspector, tmp_path: Path):
    capture._REGISTRY[1] = capture.SourceInfo(
        file="/abs/foo.py", line=3, column=1, component="Foo"
    )
    capture._REGISTRY[2] = capture.SourceInfo(
        file="/abs/bar.py", line=5, column=2, component="Bar"
    )

    out = emit.write_source_map(tmp_path)
    assert out is not None
    assert out == tmp_path / emit.SOURCE_MAP_DIRNAME / emit.SOURCE_MAP_FILENAME

    payload = json.loads(out.read_text())
    assert payload == {
        "1": {"file": "/abs/foo.py", "line": 3, "column": 1, "component": "Foo"},
        "2": {"file": "/abs/bar.py", "line": 5, "column": 2, "component": "Bar"},
    }


def test_write_source_map_creates_directory(enabled_inspector, tmp_path: Path):
    nested = tmp_path / "deep" / "public"
    out = emit.write_source_map(nested)
    assert out is not None
    assert out.parent.is_dir()
    assert json.loads(out.read_text()) == {}
