"""Unit tests for target-aware package.json constants.

Covers `packages/reflex-base/src/reflex_base/constants/installer.py`:
- target-aware dependencies / dev_dependencies tables
- target-aware dev/export commands
"""

from __future__ import annotations

import pytest
from reflex_base.constants import FRONTEND_TARGETS
from reflex_base.constants.installer import PackageJson


def test_dependencies_for_react_router_includes_react_router():
    deps = PackageJson.dependencies_for("react_router")
    assert "react-router" in deps
    assert "react-router-dom" in deps
    assert "@react-router/node" in deps
    assert "react" in deps
    assert "socket.io-client" in deps
    assert "zustand" in deps  # shared baseline now uses Zustand


def test_dependencies_for_react_router_excludes_astro():
    deps = PackageJson.dependencies_for("react_router")
    assert "astro" not in deps
    assert "@astrojs/react" not in deps


def test_dependencies_for_astro_includes_astro():
    deps = PackageJson.dependencies_for("astro")
    assert "astro" in deps
    assert "@astrojs/react" in deps
    # shared baseline still applies
    assert "react" in deps
    assert "react-dom" in deps
    assert "socket.io-client" in deps
    assert "zustand" in deps


def test_dependencies_for_astro_excludes_react_router():
    deps = PackageJson.dependencies_for("astro")
    assert "react-router" not in deps
    assert "react-router-dom" not in deps
    assert "@react-router/node" not in deps


def test_dependencies_default_classproperty_matches_react_router():
    """The legacy class-level DEPENDENCIES property mirrors the react_router target."""
    assert PackageJson.dependencies_for("react_router") == PackageJson.DEPENDENCIES


def test_commands_for_react_router():
    commands = PackageJson.commands_for("react_router")
    assert commands == {
        "dev": "react-router dev --host",
        "export": "react-router build",
    }


def test_commands_for_astro():
    commands = PackageJson.commands_for("astro")
    assert commands == {"dev": "astro dev --host", "export": "astro build"}


def test_dev_dependencies_for_react_router_includes_react_router_dev():
    deps = PackageJson.dev_dependencies_for("react_router")
    assert "@react-router/dev" in deps
    assert "@react-router/fs-routes" in deps
    assert "vite" in deps


def test_dev_dependencies_for_astro_excludes_react_router_dev():
    deps = PackageJson.dev_dependencies_for("astro")
    assert "@react-router/dev" not in deps
    assert "@react-router/fs-routes" not in deps
    # Astro brings its own Vite; we should not pin a separate one.
    assert "vite" not in deps


@pytest.mark.parametrize("bad_target", ["next", "remix", "", "REACT_ROUTER"])
def test_dependencies_for_unknown_target_raises(bad_target: str):
    with pytest.raises(ValueError, match="Unknown frontend_target"):
        PackageJson.dependencies_for(bad_target)


@pytest.mark.parametrize("bad_target", ["next", "remix", "", "REACT_ROUTER"])
def test_commands_for_unknown_target_raises(bad_target: str):
    with pytest.raises(ValueError, match="Unknown frontend_target"):
        PackageJson.commands_for(bad_target)


@pytest.mark.parametrize("bad_target", ["next", "remix", "", "REACT_ROUTER"])
def test_dev_dependencies_for_unknown_target_raises(bad_target: str):
    with pytest.raises(ValueError, match="Unknown frontend_target"):
        PackageJson.dev_dependencies_for(bad_target)


def test_frontend_targets_constant_matches_supported_targets():
    """The exported FRONTEND_TARGETS tuple is the source of truth used by validation."""
    assert set(FRONTEND_TARGETS) == {"react_router", "astro"}
