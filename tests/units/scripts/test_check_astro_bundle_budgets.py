"""Unit tests for the Astro bundle-budget CI script.

Covers ``scripts/check_astro_bundle_budgets.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_astro_bundle_budgets.py"


def _import_script():
    """Import the script as a module (it lives outside the package layout).

    Returns:
        The loaded ``check_astro_bundle_budgets`` module object.
    """
    spec = importlib.util.spec_from_file_location(
        "check_astro_bundle_budgets", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_astro_bundle_budgets"] = module
    spec.loader.exec_module(module)
    return module


def _build_dist(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    """Materialize a fake Astro dist on disk.

    Args:
        tmp_path: pytest tmp_path fixture root.
        files: mapping of relative path to file contents.

    Returns:
        The dist root.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    for rel, contents in files.items():
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            target.write_bytes(contents)
        else:
            target.write_text(contents)
    return dist


def test_static_page_passes_with_zero_js(tmp_path: Path):
    """A static page with no scripts/css passes the default budget."""
    mod = _import_script()
    dist = _build_dist(
        tmp_path,
        {
            "index.html": (
                "<!doctype html><html><head></head><body><h1>hi</h1></body></html>"
            ),
        },
    )
    reports = mod.check_dist(dist)
    assert len(reports) == 1
    assert reports[0].render_mode == "static"
    assert reports[0].js_gzip_bytes == 0
    assert reports[0].passed is True


def test_static_page_with_inline_color_mode_script_still_passes(tmp_path: Path):
    """The color-mode head script (`(function...`) is not counted as Reflex JS."""
    mod = _import_script()
    html = (
        "<!doctype html><html><head>"
        "<script>(function () { var x = 1; })();</script>"
        "</head><body><h1>hi</h1></body></html>"
    )
    dist = _build_dist(tmp_path, {"index.html": html})
    reports = mod.check_dist(dist)
    assert reports[0].js_gzip_bytes == 0
    assert reports[0].render_mode == "static"
    assert reports[0].passed is True


def test_static_page_fails_when_js_present(tmp_path: Path):
    """A static page that ships a real <script src> exceeds the budget."""
    mod = _import_script()
    big_js = b"console.log('hello');" * 4000
    dist = _build_dist(
        tmp_path,
        {
            "index.html": (
                "<!doctype html><html><head>"
                '<meta name="reflex-render-mode" content="static">'
                '<script src="/runtime.js"></script>'
                "</head><body></body></html>"
            ),
            "runtime.js": big_js,
        },
    )
    reports = mod.check_dist(dist)
    assert reports[0].render_mode == "static"
    assert reports[0].passed is False
    assert any("JS gzip" in v for v in reports[0].violations)


def test_app_page_within_budget(tmp_path: Path):
    """An app page with a small JS chunk passes its budget."""
    mod = _import_script()
    dist = _build_dist(
        tmp_path,
        {
            "index.html": (
                "<!doctype html><html><head>"
                '<meta name="reflex-render-mode" content="app">'
                '<script src="/_astro/island.js"></script>'
                "</head><body></body></html>"
            ),
            "_astro/island.js": b"x = 1;" * 200,
        },
    )
    reports = mod.check_dist(dist)
    assert reports[0].render_mode == "app"
    assert reports[0].passed is True


def test_islands_render_mode_explicit_meta(tmp_path: Path):
    """An explicit <meta name=reflex-render-mode> wins over heuristics."""
    mod = _import_script()
    dist = _build_dist(
        tmp_path,
        {
            "index.html": (
                "<!doctype html><html><head>"
                '<meta name="reflex-render-mode" content="islands">'
                "</head><body></body></html>"
            ),
        },
    )
    reports = mod.check_dist(dist)
    assert reports[0].render_mode == "islands"
    assert reports[0].passed is True


def test_check_dist_returns_empty_for_empty_tree(tmp_path: Path):
    """No HTML files = empty report list, exits 0."""
    mod = _import_script()
    dist = tmp_path / "dist"
    dist.mkdir()
    reports = mod.check_dist(dist)
    assert reports == []


def test_main_skips_when_dist_missing(tmp_path: Path, capsys: pytest.CaptureFixture):
    """The CLI exits 0 with a message when dist is missing (non-strict)."""
    mod = _import_script()
    rc = mod.main(["--dist", str(tmp_path / "missing")])
    assert rc == 0
    captured = capsys.readouterr()
    assert "skipping" in captured.out.lower()


def test_main_strict_fails_when_dist_missing(tmp_path: Path):
    """--strict turns missing-dist into a hard failure."""
    mod = _import_script()
    rc = mod.main(["--dist", str(tmp_path / "missing"), "--strict"])
    assert rc == 1


def test_main_passes_with_default_dist(tmp_path: Path):
    """An empty dist with the default budgets passes."""
    mod = _import_script()
    dist = tmp_path / "dist"
    dist.mkdir()
    rc = mod.main(["--dist", str(dist)])
    assert rc == 0


def test_main_fails_on_static_with_js(tmp_path: Path):
    """A static-meta page with external JS makes the CLI exit 1."""
    mod = _import_script()
    big_js = b"console.log('z');" * 5000
    dist = _build_dist(
        tmp_path,
        {
            "index.html": (
                "<!doctype html><html><head>"
                '<meta name="reflex-render-mode" content="static">'
                '<script src="/r.js"></script>'
                "</head><body></body></html>"
            ),
            "r.js": big_js,
        },
    )
    rc = mod.main(["--dist", str(dist)])
    assert rc == 1
