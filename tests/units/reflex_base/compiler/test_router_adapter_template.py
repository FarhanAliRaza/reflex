"""Unit tests for the per-target router adapter templates.

Covers ``packages/reflex-base/src/reflex_base/compiler/router_adapter_template.py``.
"""

from __future__ import annotations

import pytest
from reflex_base.compiler.router_adapter_template import (
    astro_router_adapter_template,
    react_router_adapter_template,
    router_adapter_template_for,
)


def test_react_router_adapter_imports_react_router_hooks():
    src = react_router_adapter_template()
    assert 'from "react-router"' in src
    for hook in ("useLocation", "useNavigate", "useParams", "useSearchParams"):
        assert hook in src


def test_react_router_adapter_exports_use_router_adapter():
    src = react_router_adapter_template()
    assert "export const useRouterAdapter" in src
    # Returns location/navigate/params/searchParams.
    assert "location" in src
    assert "navigate" in src
    assert "params" in src
    assert "searchParams" in src


def test_astro_router_adapter_does_not_import_react_router():
    """The Astro adapter must not import anything from react-router."""
    src = astro_router_adapter_template()
    assert "react-router" not in src
    assert 'from "react-router' not in src


def test_astro_router_adapter_uses_native_browser_apis():
    src = astro_router_adapter_template()
    assert "window.location" in src
    assert "window.history" in src
    assert "popstate" in src


def test_astro_router_adapter_is_ssr_safe():
    """SSR pass must not crash — every browser-only access is gated."""
    src = astro_router_adapter_template()
    assert 'typeof window === "undefined"' in src
    # Server-side defaults so consumers (state.js useEventLoop) don't crash.
    assert "_IS_SERVER" in src
    # Returns sensible defaults for location / params / searchParams.
    assert 'pathname: "/"' in src
    assert 'new URLSearchParams("")' in src


def test_astro_router_adapter_patches_pushstate_replacestate():
    """Astro adapter monkey-patches history so SPA navigations re-render."""
    src = astro_router_adapter_template()
    assert "pushState" in src
    assert "replaceState" in src
    assert "__REFLEX_HISTORY_PATCHED__" in src


def test_router_adapter_template_for_react_router():
    src = router_adapter_template_for("react_router")
    assert 'from "react-router"' in src


def test_router_adapter_template_for_astro():
    src = router_adapter_template_for("astro")
    assert "react-router" not in src
    assert "window.location" in src


def test_router_adapter_template_for_unknown_target_raises():
    with pytest.raises(ValueError, match="Unknown frontend_target"):
        router_adapter_template_for("nextjs")
