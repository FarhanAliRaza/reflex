"""Tests for deploy() and launch()."""

from __future__ import annotations

import ast
import importlib
import subprocess
from pathlib import Path

import pytest

from reflex.notebook import widgets
from reflex.notebook.deploy import current_launch, deploy, launch, stop
from reflex.notebook.runtime import get_runtime

deploy_module = importlib.import_module("reflex.notebook.deploy")


def test_deploy_writes_app_files(tmp_path: Path) -> None:
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    widgets.select(["A", "B"], label="Category")
    target = tmp_path / "out"
    url = deploy(app_name="my_nb", target_dir=target)
    assert url.startswith("http")
    assert (target / "rxconfig.py").exists()
    assert (target / "requirements.txt").exists()
    app_path = target / "my_nb" / "my_nb.py"
    assert app_path.exists()
    ast.parse(app_path.read_text())


def test_deploy_creates_directory_if_missing(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper"
    url = deploy(app_name="x", target_dir=target)
    assert target.exists()
    assert (target / "x" / "x.py").exists()
    assert url


class _FakeProc:
    """Stand-in for subprocess.Popen used in launch tests."""

    def __init__(self, cmd: list[str], **_: object) -> None:
        self.cmd = cmd
        self.stdout = None
        self._alive = True
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated += 1
        self._alive = False

    def kill(self) -> None:
        self.killed += 1
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        self._alive = False
        return 0


@pytest.fixture
def _stop_any_running():
    yield
    stop()


@pytest.mark.usefixtures("_stop_any_running")
def test_launch_spawns_reflex_run_with_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[_FakeProc] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> _FakeProc:
        proc = _FakeProc(cmd, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setattr(deploy_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(deploy_module, "_find_reflex_cli", lambda: "reflex")
    target = tmp_path / "app"
    url = launch(
        app_name="demo",
        target_dir=target,
        frontend_port=3500,
        backend_port=8500,
    )
    assert url == "http://localhost:3500"
    assert len(captured) == 1
    cmd = captured[0].cmd
    assert cmd[:2] == ["reflex", "run"]
    assert "--frontend-port" in cmd
    assert cmd[cmd.index("--frontend-port") + 1] == "3500"
    assert cmd[cmd.index("--backend-port") + 1] == "8500"
    snapshot = current_launch()
    assert snapshot["url"] == url
    assert snapshot["base"] == target


@pytest.mark.usefixtures("_stop_any_running")
def test_launch_terminates_prior_server_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    procs: list[_FakeProc] = []
    monkeypatch.setattr(
        deploy_module.subprocess,
        "Popen",
        lambda cmd, **kw: procs.append(_FakeProc(cmd, **kw)) or procs[-1],
    )
    monkeypatch.setattr(deploy_module, "_find_reflex_cli", lambda: "reflex")
    launch(app_name="a", target_dir=tmp_path / "a")
    launch(app_name="b", target_dir=tmp_path / "b")
    assert procs[0].terminated == 1
    assert procs[1].terminated == 0


def test_stop_terminates_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        deploy_module.subprocess,
        "Popen",
        lambda cmd, **kw: _FakeProc(cmd, **kw),
    )
    monkeypatch.setattr(deploy_module, "_find_reflex_cli", lambda: "reflex")
    launch(app_name="x", target_dir=tmp_path / "x")
    stop()
    assert current_launch()["proc"] is None


@pytest.mark.usefixtures("_stop_any_running")
def test_launch_kills_process_when_terminate_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _StubbornProc(_FakeProc):
        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="reflex", timeout=timeout or 5)

    proc_holder: list[_StubbornProc] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> _StubbornProc:
        proc = _StubbornProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    monkeypatch.setattr(deploy_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(deploy_module, "_find_reflex_cli", lambda: "reflex")
    launch(app_name="a", target_dir=tmp_path / "a")
    stop()
    assert proc_holder[0].killed == 1
