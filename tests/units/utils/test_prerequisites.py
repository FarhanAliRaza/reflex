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


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [(None, True), ("", True), ("0", False), ("pages", False), ("all", True)],
)
def test_stage_app_imports_env_gating(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected: bool
):
    """``REFLEX_ARENA_CONSTRUCT`` gates the import-time construction scope."""
    if env_value is None:
        monkeypatch.delenv("REFLEX_ARENA_CONSTRUCT", raising=False)
    else:
        monkeypatch.setenv("REFLEX_ARENA_CONSTRUCT", env_value)
    assert prerequisites._stage_app_imports() is expected


@pytest.mark.parametrize(
    ("env_value", "staged"), [(None, True), ("pages", False), ("0", False)]
)
def test_get_app_stages_import_time_constructions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_value: str | None,
    staged: bool,
):
    """The app import runs under the arena scope by default.

    A module-level ``Component.create`` must mirror + stage its var harvest
    (``_vars_cache``) under the default, and stay on the rich path under
    ``REFLEX_ARENA_CONSTRUCT=0`` / ``=pages``.
    """
    if env_value is None:
        monkeypatch.delenv("REFLEX_ARENA_CONSTRUCT", raising=False)
    else:
        monkeypatch.setenv("REFLEX_ARENA_CONSTRUCT", env_value)
    module_name = f"arena_import_probe_{env_value or 'default'}"
    (tmp_path / f"{module_name}.py").write_text(
        "import reflex as rx\n"
        "from reflex_base.components.component import _ARENA_CONSTRUCTION\n"
        "SCOPE = _ARENA_CONSTRUCTION.get()\n"
        "COMP = rx.box(background_color='red')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config = types.SimpleNamespace(
        _app_name_is_valid=True, module=module_name, app_module=None
    )
    monkeypatch.setattr(prerequisites, "get_config", lambda: config)
    module = prerequisites.get_app()
    assert module.SCOPE is staged
    assert ("_vars_cache" in module.COMP.__dict__) is staged
