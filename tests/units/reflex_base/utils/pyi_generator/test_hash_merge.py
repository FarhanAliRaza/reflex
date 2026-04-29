"""Tests for ``pyi_hashes.json`` merge behavior in ``PyiGenerator.scan_all``."""

from __future__ import annotations

import json
from pathlib import Path

from reflex_base.utils.pyi_generator import PyiGenerator


def _write_hashes(path: Path, mapping: dict[str, str]) -> None:
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")


def _make_workspace(root: Path) -> Path:
    """Lay out a fake workspace with a couple of source files and a hash file.

    Args:
        root: tmp directory to populate.

    Returns:
        The workspace root.
    """
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "foo.py").write_text("# placeholder\n")
    (pkg / "bar.py").write_text("# placeholder\n")
    other = root / "other"
    other.mkdir()
    (other / "baz.py").write_text("# placeholder\n")
    return root


def test_partial_run_preserves_unrelated_entries(tmp_path, monkeypatch):
    """Entries for files outside the run's scope are preserved."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    _write_hashes(
        hashes_path,
        {
            "pkg/foo.pyi": "OLD_FOO",
            "pkg/bar.pyi": "BAR",
            "other/baz.pyi": "BAZ",
        },
    )

    foo_pyi = (workspace / "pkg" / "foo.py").with_suffix(".pyi").resolve()

    def fake_scan(self, files):
        self.written_files.append((str(foo_pyi), "NEW_FOO"))

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(["pkg/foo.py"], changed_files=None, use_json=True)

    result = json.loads(hashes_path.read_text())
    assert result == {
        "pkg/foo.pyi": "NEW_FOO",
        "pkg/bar.pyi": "BAR",
        "other/baz.pyi": "BAZ",
    }


def test_scanned_file_with_no_output_drops_entry(tmp_path, monkeypatch):
    """A file scanned this run that produces no stub has its hash entry removed."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    _write_hashes(
        hashes_path,
        {
            "pkg/foo.pyi": "OLD_FOO",
            "pkg/bar.pyi": "BAR",
        },
    )

    bar_pyi = (workspace / "pkg" / "bar.py").with_suffix(".pyi").resolve()

    def fake_scan(self, files):
        self.written_files.append((str(bar_pyi), "BAR_NEW"))

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(["pkg/foo.py", "pkg/bar.py"], changed_files=None, use_json=True)

    result = json.loads(hashes_path.read_text())
    assert result == {"pkg/bar.pyi": "BAR_NEW"}


def test_single_scanned_file_with_no_output_drops_entry(tmp_path, monkeypatch):
    """Scanning one file that produces no stub still drops its old hash entry."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    _write_hashes(
        hashes_path,
        {
            "pkg/foo.pyi": "OLD_FOO",
            "pkg/bar.pyi": "BAR",
        },
    )

    def fake_scan(self, files):
        return

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(["pkg/foo.py"], changed_files=None, use_json=True)

    result = json.loads(hashes_path.read_text())
    assert result == {"pkg/bar.pyi": "BAR"}


def test_creates_hashes_file_when_missing(tmp_path, monkeypatch):
    """If ``pyi_hashes.json`` doesn't exist, the merge creates it."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    assert not hashes_path.exists()

    foo_pyi = (workspace / "pkg" / "foo.py").with_suffix(".pyi").resolve()

    def fake_scan(self, files):
        self.written_files.append((str(foo_pyi), "FOO"))

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(["pkg/foo.py"], changed_files=None, use_json=True)

    assert hashes_path.exists()
    assert json.loads(hashes_path.read_text()) == {"pkg/foo.pyi": "FOO"}


def test_missing_source_file_drops_entry(tmp_path, monkeypatch):
    """An entry whose source ``.py`` no longer exists is cleaned up."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    _write_hashes(
        hashes_path,
        {
            "pkg/foo.pyi": "FOO",
            "pkg/deleted.pyi": "STALE",
        },
    )

    foo_pyi = (workspace / "pkg" / "foo.py").with_suffix(".pyi").resolve()

    def fake_scan(self, files):
        self.written_files.append((str(foo_pyi), "FOO_NEW"))

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(["pkg/foo.py"], changed_files=None, use_json=True)

    result = json.loads(hashes_path.read_text())
    assert result == {"pkg/foo.pyi": "FOO_NEW"}


def test_incremental_run_merges_into_existing(tmp_path, monkeypatch):
    """An incremental run (``changed_files`` set) merges new hashes into the existing file."""
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)

    hashes_path = workspace / "pyi_hashes.json"
    _write_hashes(
        hashes_path,
        {
            "pkg/foo.pyi": "OLD_FOO",
            "pkg/bar.pyi": "BAR",
        },
    )

    foo_pyi = (workspace / "pkg" / "foo.py").with_suffix(".pyi").resolve()

    def fake_scan(self, files):
        self.written_files.append((str(foo_pyi), "NEW_FOO"))

    monkeypatch.setattr(PyiGenerator, "_scan_files", fake_scan)

    gen = PyiGenerator()
    gen.scan_all(
        ["pkg/foo.py"],
        changed_files=[Path("pkg/foo.py")],
        use_json=True,
    )

    result = json.loads(hashes_path.read_text())
    assert result == {
        "pkg/foo.pyi": "NEW_FOO",
        "pkg/bar.pyi": "BAR",
    }
