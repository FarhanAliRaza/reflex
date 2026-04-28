"""Coordinator between Reflex's compile pipeline and the inspector.

Other code should call into this module rather than the underlying pieces
(``capture`` / ``emit`` / ``state`` / ``shortcut`` / asset directory) so the
inspector's lifecycle has a single canonical shape:

  1. ``prepare_for_compile`` — flip the runtime state flag and clear stale
     capture data at the start of each compile.
  2. ``package_json_dev_dependencies`` / ``head_components`` /
     ``plugin_text`` — declarative inputs to the compile-time templates.
  3. ``asset_source_dir`` — where browser assets live on disk; the host
     package copies them into ``.web/public``.
  4. ``write_source_map`` — emit the lookup table after pages render.

``frontend_inspector="dev"`` is a no-op when ``REFLEX_ENV_MODE=prod`` so the
same ``rxconfig.py`` can be reused across dev and prod runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from reflex_base import constants
from reflex_base.environment import environment

from . import (
    EDITOR_URL,
    INSPECTOR_CSS_URL,
    INSPECTOR_JS_URL,
    SHORTCUT_CONFIG_KEY,
    SOURCE_MAP_URL,
    WINDOW_CONFIG_KEY,
    capture,
    emit,
    state,
)

if TYPE_CHECKING:
    from reflex_base.components.component import Component
    from reflex_base.config import Config

LAUNCH_EDITOR_VERSION = "^2.6.1"


def is_active(config: Config) -> bool:
    """Whether the inspector should emit wiring for the current build.

    The config alone is not enough: ``REFLEX_ENV_MODE`` may flip to ``prod``
    after ``Config()`` was constructed (``reflex export`` does this), so we
    re-check the runtime env mode at every emission site.

    Args:
        config: The current Reflex config.

    Returns:
        True iff ``frontend_inspector != "off"`` and the build target is dev.
    """
    if config.frontend_inspector == "off":
        return False
    return environment.REFLEX_ENV_MODE.get() != constants.Env.PROD


def prepare_for_compile(config: Config) -> None:
    """Sync runtime state at the start of a compile pass.

    This is the single integration point the host's compile path should
    call. After this returns, ``state.is_enabled()`` reflects the current
    build target and the registry is empty (so HMR rebuilds don't
    accumulate stale entries).

    Args:
        config: The current Reflex config.
    """
    active = is_active(config)
    state.set_enabled(active)
    if active:
        capture.reset()


def package_json_dev_dependencies(config: Config) -> dict[str, str]:
    """Extra dev dependencies to merge into ``package.json``.

    Args:
        config: The current Reflex config.

    Returns:
        ``{"launch-editor": "..."}`` when active, otherwise ``{}``.
    """
    if not is_active(config):
        return {}
    return {"launch-editor": LAUNCH_EDITOR_VERSION}


def head_components(config: Config) -> list[Component]:
    """The ``<script>`` tags to inject into the document head.

    React Router 7 renders HTML through React rather than serving a static
    ``index.html``, so Vite's ``transformIndexHtml`` hook never fires for
    app routes. Injecting via the document root is the equivalent for that
    target.

    Args:
        config: The current Reflex config.

    Returns:
        The inspector head scripts, or an empty list when inactive.
    """
    if not is_active(config):
        return []

    from reflex_components_core.el.elements.scripts import Script

    from .shortcut import parse_shortcut

    shortcut = parse_shortcut(config.frontend_inspector_shortcut)
    payload = json.dumps({
        SHORTCUT_CONFIG_KEY: shortcut.to_json_payload(),
        "sourceMapUrl": config.prepend_frontend_path(SOURCE_MAP_URL),
        "cssUrl": config.prepend_frontend_path(INSPECTOR_CSS_URL),
        "editorUrl": config.prepend_frontend_path(EDITOR_URL),
    })
    return [
        Script.create(f"window.{WINDOW_CONFIG_KEY} = {payload};"),
        Script.create(
            type="module", src=config.prepend_frontend_path(INSPECTOR_JS_URL)
        ),
    ]


def plugin_text(config: Config) -> str:
    """Render the Vite plugin file content.

    Args:
        config: The current Reflex config.

    Returns:
        The rendered plugin source.
    """
    from reflex_base.compiler.inspector_plugins import vite_plugin_template

    return vite_plugin_template(editor=config.frontend_inspector_editor)


def asset_source_dir() -> Path:
    """Directory containing the bundled inspector browser assets.

    Returns:
        Absolute path to ``reflex_base/assets/inspector``.
    """
    import reflex_base

    return Path(reflex_base.__file__).resolve().parent / "assets" / "inspector"


def write_source_map(public_dir: Path) -> Path | None:
    """Emit the source map after all pages have been rendered.

    Args:
        public_dir: The static-served public directory, e.g. ``.web/public``.

    Returns:
        The path that was written, or ``None`` when the inspector is
        inactive.
    """
    return emit.write_source_map(public_dir)
