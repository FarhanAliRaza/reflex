"""Byte-parity gate for the Var implementation against the golden oracle.

This replays the exact expression corpus captured by
``scripts/capture_var_golden.py`` (both share ``_var_corpus.py``) and asserts
the *current* ``Var`` implementation reproduces the frozen ``_js_expr`` /
``_var_type`` / ``_get_all_var_data()`` byte-for-byte.

Today it guards the Python ``Var`` against regressions. It is also the
**acceptance gate for the Rust Var cutover**: when ``Var`` is reimplemented in
Rust, this same corpus and these same assertions run unchanged — only the
``Var`` underneath flips. The cutover is "done" (for the surface this corpus
covers) exactly when this stays green with the Rust ``Var`` in place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.units.vars._var_corpus import _corpus, _record

GOLDEN_PATH = Path(__file__).resolve().parent / "var_golden.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    """Load the frozen golden output.

    Returns:
        The parsed golden fixture mapping.
    """
    return json.loads(GOLDEN_PATH.read_text())


def test_corpus_matches_golden_keys(golden: dict) -> None:
    """The live corpus and the golden file must cover the same expressions."""
    assert set(_corpus()) == set(golden)


@pytest.mark.parametrize("key", sorted(_corpus()))
def test_var_renders_golden(key: str, golden: dict) -> None:
    """Each corpus expression must render byte-identically to the golden."""
    assert _record(_corpus()[key]()) == golden[key]
