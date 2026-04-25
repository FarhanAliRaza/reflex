"""File for constants related to the installation process. (Bun/Node)."""

from __future__ import annotations

import os
from types import SimpleNamespace

from .base import IS_WINDOWS
from .utils import classproperty


# Bun config.
class Bun(SimpleNamespace):
    """Bun constants."""

    # The Bun version.
    VERSION = "1.3.10"

    # Min Bun Version
    MIN_VERSION = "1.3.0"

    # URL to bun install script.
    INSTALL_URL = "https://raw.githubusercontent.com/reflex-dev/reflex/main/scripts/bun_install.sh"

    # URL to windows install script.
    WINDOWS_INSTALL_URL = (
        "https://raw.githubusercontent.com/reflex-dev/reflex/main/scripts/install.ps1"
    )

    # Path of the bunfig file
    CONFIG_PATH = "bunfig.toml"

    @classproperty
    @classmethod
    def ROOT_PATH(cls):
        """The directory to store the bun.

        Returns:
            The directory to store the bun.
        """
        from reflex_base.environment import environment

        return environment.REFLEX_DIR.get() / "bun"

    @classproperty
    @classmethod
    def DEFAULT_PATH(cls):
        """Default bun path.

        Returns:
            The default bun path.
        """
        return cls.ROOT_PATH / "bin" / ("bun" if not IS_WINDOWS else "bun.exe")

    DEFAULT_CONFIG = """
[install]
registry = "{registry}"
"""


# Node / NPM config
class Node(SimpleNamespace):
    """Node/ NPM constants."""

    # The minimum required node version.
    MIN_VERSION = "20.19.0"

    # Path of the node config file.
    CONFIG_PATH = ".npmrc"

    DEFAULT_CONFIG = """
registry={registry}
fetch-retries=0
"""


def _determine_react_router_version() -> str:
    default_version = "7.13.1"
    if (version := os.getenv("REACT_ROUTER_VERSION")) and version != default_version:
        from reflex_base.utils import console

        console.warn(
            f"You have requested react-router@{version} but the supported version is {default_version}, abandon all hope ye who enter here."
        )
        return version
    return default_version


def _determine_react_version() -> str:
    default_version = "19.2.4"
    if (version := os.getenv("REACT_VERSION")) and version != default_version:
        from reflex_base.utils import console

        console.warn(
            f"You have requested react@{version} but the supported version is {default_version}, abandon all hope ye who enter here."
        )
        return version
    return default_version


class PackageJson(SimpleNamespace):
    """Constants used to build the package.json file."""

    class Commands(SimpleNamespace):
        """The commands to define in package.json."""

        @classproperty
        @classmethod
        def DEV(cls) -> str:
            """Return the frontend dev command for the active target."""
            del cls
            return (
                "astro dev --host"
                if _get_frontend_target() == "astro"
                else "react-router dev --host"
            )

        @classproperty
        @classmethod
        def EXPORT(cls) -> str:
            """Return the frontend export/build command for the active target."""
            del cls
            return "astro build" if _get_frontend_target() == "astro" else "react-router build"

    PATH = "package.json"

    _react_version = _determine_react_version()

    _react_router_version = _determine_react_router_version()

    @classproperty
    @classmethod
    def DEPENDENCIES(cls) -> dict[str, str]:
        """The dependencies to include in package.json.

        Returns:
            A dictionary of dependencies with their versions.
        """
        dependencies = {
            "json5": "2.2.3",
            "react": cls._react_version,
            "react-helmet": "6.1.0",
            "react-dom": cls._react_version,
            "isbot": "5.1.36",
            "socket.io-client": "4.8.3",
            "universal-cookie": "7.2.2",
        }
        if _get_frontend_target() == "astro":
            dependencies.update(
                {
                    "astro": "5.13.8",
                    "@astrojs/react": "4.4.0",
                }
            )
            return dependencies

        dependencies.update(
            {
                "react-router": cls._react_router_version,
                "react-router-dom": cls._react_router_version,
                "@react-router/node": cls._react_router_version,
            }
        )
        return dependencies

    @classproperty
    @classmethod
    def DEV_DEPENDENCIES(cls) -> dict[str, str]:
        """The devDependencies to include in package.json.

        Returns:
            A dictionary of development dependencies with their versions.
        """
        dev_dependencies = {
            "@emotion/react": "11.14.0",
            "autoprefixer": "10.4.27",
            "postcss": "8.5.8",
            "postcss-import": "16.1.1",
            "vite": "8.0.0",
        }
        if _get_frontend_target() == "astro":
            return dev_dependencies

        dev_dependencies.update(
            {
                "@react-router/dev": cls._react_router_version,
                "@react-router/fs-routes": cls._react_router_version,
            }
        )
        return dev_dependencies
    OVERRIDES = {
        # This should always match the `react` version in DEPENDENCIES for recharts compatibility.
        "react-is": _react_version,
        "cookie": "1.1.1",
    }


def _get_frontend_target() -> str:
    """Return the configured frontend target with a safe default.

    Returns:
        The configured frontend target.
    """
    from reflex_base.config import get_config

    return getattr(get_config(), "frontend_target", "react_router")
