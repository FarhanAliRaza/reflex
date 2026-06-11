"""Tests for reflex.utils.prerequisites."""

import sys
import types
from pathlib import Path

import pytest

from reflex.utils import prerequisites


@pytest.fixture
def fake_app_config(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Point ``get_app`` at a pre-imported fake app module.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        The fake config served by ``get_config``.
    """
    config = types.SimpleNamespace(
        _app_name_is_valid=True,
        module="fake_app_module",
        app_module=types.ModuleType("fake_app_module"),
    )
    monkeypatch.setattr(prerequisites, "get_config", lambda: config)
    monkeypatch.setattr(sys, "path", list(sys.path))
    return config


def test_get_app_does_not_grow_sys_path(fake_app_config: types.SimpleNamespace):
    """Repeated ``get_app`` calls insert the cwd into sys.path at most once.

    Regression: every call inserted ``getcwd()`` unconditionally. The legacy
    memo compiler calls ``get_and_validate_app`` once per memo component
    (thousands per large app), inflating sys.path until the multiprocessing
    forkserver's command line exceeded the kernel argv limit (E2BIG) — which
    made ``reflex run-rust`` exit silently right after "Starting Reflex App".
    """
    cwd = str(Path.cwd())
    baseline = sys.path.count(cwd)
    for _ in range(5):
        prerequisites.get_app()
    assert sys.path.count(cwd) <= max(baseline, 1)
