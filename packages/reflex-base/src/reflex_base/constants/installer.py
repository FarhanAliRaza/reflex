"""File for constants related to the installation process. (Bun/Node)."""

from __future__ import annotations

import os
from types import SimpleNamespace

from .base import FrontendTarget, IS_WINDOWS
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

        DEV = "react-router dev --host"
        EXPORT = "react-router build"
        SVELTEKIT_DEV = "vite dev --host"
        SVELTEKIT_EXPORT = "vite build"

        @staticmethod
        def get_prod_command(frontend_path: str = "") -> str:
            """Get the prod command with the correct 404.html path for the given frontend_path.

            Args:
                frontend_path: The frontend path prefix (e.g. "/app").

            Returns:
                The sirv command with the correct --single fallback path.
            """
            stripped = frontend_path.strip("/")
            fallback = f"{stripped}/404.html" if stripped else "404.html"
            return f"sirv ./build/client --single {fallback} --host"

        @staticmethod
        def get_sveltekit_prod_command(frontend_path: str = "") -> str:
            """Get the static sirv command for SvelteKit output.

            Args:
                frontend_path: The frontend path prefix (e.g. "/app").

            Returns:
                The sirv command with the correct SPA fallback path.
            """
            stripped = frontend_path.strip("/")
            fallback = f"{stripped}/200.html" if stripped else "200.html"
            return f"sirv ./build/client --single {fallback} --host"

    PATH = "package.json"

    _react_version = _determine_react_version()

    _react_router_version = _determine_react_router_version()

    @staticmethod
    def _normalize_target(
        frontend_target: FrontendTarget | str,
    ) -> str:
        if isinstance(frontend_target, FrontendTarget):
            return frontend_target.value
        return frontend_target

    @classproperty
    @classmethod
    def DEPENDENCIES(cls) -> dict[str, str]:
        """The dependencies to include in package.json.

        Returns:
            A dictionary of dependencies with their versions.
        """
        return {
            "json5": "2.2.3",
            "react-router": cls._react_router_version,
            "react-router-dom": cls._react_router_version,
            "@react-router/node": cls._react_router_version,
            "sirv-cli": "3.0.1",
            "react": cls._react_version,
            "react-helmet": "6.1.0",
            "react-dom": cls._react_version,
            "isbot": "5.1.36",
            "socket.io-client": "4.8.3",
            "universal-cookie": "7.2.2",
        }

    @classproperty
    @classmethod
    def SVELTEKIT_DEPENDENCIES(cls) -> dict[str, str]:
        """Dependencies for the SvelteKit frontend target."""
        return {
            "@radix-ui/themes": "3.3.0",
            "bits-ui": "2.9.6",
            "clsx": "2.1.1",
            "json5": "2.2.3",
            "lucide-svelte": "0.577.0",
            "socket.io-client": "4.8.3",
            "svelte": "5.38.6",
            "universal-cookie": "7.2.2",
        }

    DEV_DEPENDENCIES = {
        "@emotion/react": "11.14.0",
        "autoprefixer": "10.4.27",
        "postcss": "8.5.8",
        "postcss-import": "16.1.1",
        "@react-router/dev": _react_router_version,
        "@react-router/fs-routes": _react_router_version,
        "vite": "8.0.0",
    }
    SVELTEKIT_DEV_DEPENDENCIES = {
        "@sveltejs/adapter-static": "3.0.9",
        "@sveltejs/kit": "2.37.0",
        "@sveltejs/vite-plugin-svelte": "6.1.4",
        "@tailwindcss/postcss": "4.1.12",
        "autoprefixer": "10.4.27",
        "postcss": "8.5.8",
        "postcss-import": "16.1.1",
        "sirv-cli": "3.0.1",
        "tailwindcss": "4.1.12",
        "vite": "8.0.0",
    }
    OVERRIDES = {
        # This should always match the `react` version in DEPENDENCIES for recharts compatibility.
        "react-is": _react_version,
        "cookie": "1.1.1",
    }

    @classmethod
    def get_scripts(
        cls,
        frontend_target: FrontendTarget | str,
        frontend_path: str = "",
    ) -> dict[str, str]:
        """Get scripts for the chosen frontend target."""
        target = cls._normalize_target(frontend_target)
        if target == FrontendTarget.SVELTEKIT.value:
            return {
                "dev": cls.Commands.SVELTEKIT_DEV,
                "export": cls.Commands.SVELTEKIT_EXPORT,
                "prod": cls.Commands.get_sveltekit_prod_command(frontend_path),
            }
        return {
            "dev": cls.Commands.DEV,
            "export": cls.Commands.EXPORT,
            "prod": cls.Commands.get_prod_command(frontend_path),
        }

    @classmethod
    def get_dependencies(cls, frontend_target: FrontendTarget | str) -> dict[str, str]:
        """Get dependencies for the chosen frontend target."""
        target = cls._normalize_target(frontend_target)
        if target == FrontendTarget.SVELTEKIT.value:
            return cls.SVELTEKIT_DEPENDENCIES
        return cls.DEPENDENCIES

    @classmethod
    def get_dev_dependencies(
        cls, frontend_target: FrontendTarget | str
    ) -> dict[str, str]:
        """Get development dependencies for the chosen frontend target."""
        target = cls._normalize_target(frontend_target)
        if target == FrontendTarget.SVELTEKIT.value:
            return cls.SVELTEKIT_DEV_DEPENDENCIES
        return cls.DEV_DEPENDENCIES

    @classmethod
    def get_overrides(cls, frontend_target: FrontendTarget | str) -> dict[str, str]:
        """Get overrides for the chosen frontend target."""
        target = cls._normalize_target(frontend_target)
        if target == FrontendTarget.SVELTEKIT.value:
            return {}
        return cls.OVERRIDES
