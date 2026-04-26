"""Unit tests for target-aware constants in `reflex_base.constants.base`."""

from __future__ import annotations

import re

from reflex_base.constants import FRONTEND_TARGETS
from reflex_base.constants.base import Astro, ReactRouter


def test_frontend_targets_tuple():
    assert FRONTEND_TARGETS == ("react_router", "astro")


def test_react_router_listening_regex_matches_vite_form():
    """Vite (React Router target) prints `Local:  http://...`."""
    line = "  ➜  Local:  http://localhost:3000/"
    assert re.search(ReactRouter.FRONTEND_LISTENING_REGEX, line)


def test_react_router_listening_regex_matches_astro_form():
    """Astro prints `Local    http://...` with no colon — same combined regex must match.

    AppHarness depends on the combined regex matching both dev-server outputs
    so the harness can drive the Astro target without changes.
    """
    line = "  ➜  Local    http://localhost:4321/"
    assert re.search(ReactRouter.FRONTEND_LISTENING_REGEX, line)


def test_react_router_listening_regex_matches_prod_form():
    """Production (`react-router-serve`) line is still recognized."""
    line = "INFO  Accepting connections at http://localhost:3000"
    assert re.search(ReactRouter.FRONTEND_LISTENING_REGEX, line)


def test_astro_constants():
    assert Astro.CONFIG_FILE == "astro.config.mjs"
    assert Astro.PAGES_DIR == "src/pages"
    assert Astro.LAYOUTS_DIR == "src/layouts"
    assert Astro.ISLANDS_DIR == "src/reflex/islands"
    assert Astro.BUILD_DIR == "dist"


def test_astro_dev_listening_regex():
    line = "  ➜  Local    http://localhost:4321/"
    assert re.search(Astro.DEV_FRONTEND_LISTENING_REGEX, line)
