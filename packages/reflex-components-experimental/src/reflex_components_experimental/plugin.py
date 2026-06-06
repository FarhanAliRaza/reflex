"""Plugin that ships the experimental design-token theme + its frontend deps.

Enable in ``rxconfig.py`` alongside ``TailwindV4Plugin`` (the components are
authored as Tailwind utilities):

    config = rx.Config(
        app_name="myapp",
        plugins=[
            rx.plugins.TailwindV4Plugin(),
            ExperimentalThemePlugin(),
        ],
    )
"""

from __future__ import annotations

import dataclasses
import importlib.resources
from pathlib import Path
from typing import Any

from reflex_base.constants import Dirs
from reflex_base.plugins.base import Plugin

from reflex_components_experimental.utils import CN_PACKAGE

THEME_FILENAME = "experimental-theme.css"


def _theme_css() -> str:
    """Return the packaged token-theme CSS.

    Returns:
        The contents of ``theme.css`` shipped with the package.
    """
    return (
        importlib.resources.files("reflex_components_experimental") / "theme.css"
    ).read_text(encoding="utf-8")


@dataclasses.dataclass
class ExperimentalThemePlugin(Plugin):
    """Provides the Radix-token theme stylesheet and the ``cn`` npm dependency."""

    def get_static_assets(self, **context: Any) -> list[tuple[Path, str]]:
        """Write the token theme into the web styles directory.

        Returns:
            A single ``(dest_path, css)`` pair under ``styles/``.
        """
        return [(Path(Dirs.STYLES) / THEME_FILENAME, _theme_css())]

    def get_stylesheet_paths(self, **context: Any) -> tuple[str, ...]:
        """Reference the token theme from the root stylesheet.

        Returns:
            The theme stylesheet path relative to the styles directory.
        """
        return (f"./{THEME_FILENAME}",)

    def get_frontend_dependencies(self, **context: Any) -> tuple[str, ...]:
        """Declare the npm package backing ``cn`` (clsx + tailwind-merge).

        Returns:
            The ``clsx-for-tailwind`` package spec.
        """
        return (CN_PACKAGE,)
