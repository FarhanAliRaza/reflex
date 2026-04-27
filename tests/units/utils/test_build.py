"""Tests for frontend build/export helpers."""

from types import SimpleNamespace

from pytest_mock import MockerFixture
from reflex_base import constants

from reflex.utils import build


def test_frontend_output_dir_uses_astro_dist(tmp_path):
    """Astro exports package ``.web/dist`` rather than React Router's client dir."""
    assert (
        build._frontend_output_dir(tmp_path, "astro")
        == tmp_path / constants.Astro.BUILD_DIR
    )
    assert (
        build._frontend_build_dir(tmp_path, "astro")
        == tmp_path / constants.Astro.BUILD_DIR
    )


def test_frontend_output_dir_uses_react_router_client(tmp_path):
    """React Router keeps the existing ``.web/build/client`` output."""
    assert (
        build._frontend_output_dir(tmp_path, "react_router")
        == tmp_path / constants.Dirs.STATIC
    )
    assert (
        build._frontend_build_dir(tmp_path, "react_router")
        == tmp_path / constants.Dirs.BUILD_DIR
    )


def test_postprocess_static_build_skips_react_router_steps_for_astro(
    tmp_path, monkeypatch
):
    """Astro post-build must not look for ``.web/build/client``."""
    (tmp_path / constants.Astro.BUILD_DIR).mkdir()

    def fail_duplicate(_directory):
        msg = "Astro should not run React Router post-processing"
        raise AssertionError(msg)

    monkeypatch.setattr(
        build, "_duplicate_index_html_to_parent_directory", fail_duplicate
    )

    build._postprocess_static_build(
        tmp_path,
        SimpleNamespace(frontend_target="astro").frontend_target,
        "/docs",
    )


def _stub_build_env(tmp_path, mocker: MockerFixture, captured: dict[str, object]):
    """Patch every external touchpoint of :func:`build.build` for testing.

    Captures the ``env`` dict passed to ``processes.new_process`` so the
    caller can assert how ``NODE_OPTIONS`` was assembled.
    """

    def fake_new_process(*_args, env, **_kwargs):
        captured["env"] = env
        return SimpleNamespace(wait=lambda: None, returncode=0)

    mocker.patch("reflex.utils.build.prerequisites.get_web_dir", return_value=tmp_path)
    mocker.patch(
        "reflex.utils.build.get_config",
        return_value=SimpleNamespace(
            frontend_target="astro", frontend_path="/", loglevel=SimpleNamespace()
        ),
    )
    mocker.patch("reflex.utils.build.path_ops.rm")
    mocker.patch(
        "reflex.utils.build.processes.new_process", side_effect=fake_new_process
    )
    mocker.patch("reflex.utils.build.processes.show_progress")
    mocker.patch("reflex.utils.build._postprocess_static_build")
    mocker.patch(
        "reflex.utils.js_runtimes.get_js_package_executor",
        return_value=(["bun"], None),
    )


def test_build_bumps_node_heap(tmp_path, monkeypatch, mocker: MockerFixture):
    """Frontend build must raise Node's heap limit so big sites don't OOM.

    Without ``--max-old-space-size``, sites with hundreds of routes (and
    the auto-memo wrappers each one generates) blow past Node's ~4 GB
    default during the Vite client bundle and crash with
    ``Ineffective mark-compacts near heap limit``.
    """
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    captured: dict[str, object] = {}
    _stub_build_env(tmp_path, mocker, captured)

    build.build()

    env = captured["env"]
    assert isinstance(env, dict)
    assert "--max-old-space-size=8192" in env["NODE_OPTIONS"]


def test_build_preserves_user_node_options(
    tmp_path, monkeypatch, mocker: MockerFixture
):
    """A pre-existing ``--max-old-space-size`` from the user is left alone."""
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=16384 --inspect")
    captured: dict[str, object] = {}
    _stub_build_env(tmp_path, mocker, captured)

    build.build()

    env = captured["env"]
    assert env["NODE_OPTIONS"] == "--max-old-space-size=16384 --inspect"
