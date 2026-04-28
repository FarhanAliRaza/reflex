"""Tests for frontend skeleton emission gated on the inspector mode."""

from __future__ import annotations

import json

import pytest
from reflex_base.constants import Env

import reflex as rx
from reflex.utils import frontend_skeleton


def _patch_config(monkeypatch: pytest.MonkeyPatch, **kwargs) -> rx.Config:
    config = rx.Config(app_name="test", **kwargs)
    monkeypatch.setattr(frontend_skeleton, "get_config", lambda: config)
    return config


def test_package_json_includes_launch_editor_when_inspector_active(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: launch-editor must land in package.json on every compile.

    Previously ``initialize_package_json`` only ran on first init, so
    flipping ``frontend_inspector="dev"`` later left ``package.json`` without
    the dev dep and ``bun install`` could not pull it in.
    """
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.DEV.value)
    _patch_config(monkeypatch, frontend_inspector="dev")

    payload = json.loads(frontend_skeleton._compile_package_json())
    assert "launch-editor" in payload["devDependencies"]


def test_package_json_omits_launch_editor_in_prod(
    monkeypatch: pytest.MonkeyPatch,
):
    """``frontend_inspector="dev"`` must not leak ``launch-editor`` into prod.

    Regression for the env-mode ordering bug: ``Config()`` is constructed
    before ``REFLEX_ENV_MODE`` is set in the export flow, so the gate has to
    re-check at emission time rather than at config init.
    """
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.DEV.value)
    _patch_config(monkeypatch, frontend_inspector="dev")
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.PROD.value)

    payload = json.loads(frontend_skeleton._compile_package_json())
    assert "launch-editor" not in payload["devDependencies"]


def test_vite_config_omits_inspector_in_prod(
    monkeypatch: pytest.MonkeyPatch,
):
    """Vite config must not register the inspector plugin for prod builds."""
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.DEV.value)
    config = _patch_config(monkeypatch, frontend_inspector="dev")
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.PROD.value)

    rendered = frontend_skeleton._compile_vite_config(config)
    assert "reflexInspectorPlugin" not in rendered


def test_vite_config_includes_inspector_in_dev(
    monkeypatch: pytest.MonkeyPatch,
):
    """Vite config wires the inspector plugin when env+config both allow."""
    monkeypatch.setenv("REFLEX_ENV_MODE", Env.DEV.value)
    config = _patch_config(monkeypatch, frontend_inspector="dev")

    rendered = frontend_skeleton._compile_vite_config(config)
    assert "reflexInspectorPlugin" in rendered
