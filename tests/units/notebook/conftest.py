"""Shared fixtures for the notebook unit tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from reflex.notebook.runtime import reset_runtime


@pytest.fixture(autouse=True)
def _isolated_runtime() -> Generator[None, None, None]:
    """Each test gets a fresh notebook runtime to avoid cross-test leakage.

    Yields:
        Control to the wrapped test, with a clean runtime in place.
    """
    reset_runtime()
    yield
    reset_runtime()
