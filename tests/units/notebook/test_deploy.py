"""Tests for deploy()."""

from __future__ import annotations

import ast
from pathlib import Path

from reflex.notebook import widgets
from reflex.notebook.deploy import deploy
from reflex.notebook.runtime import get_runtime


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
