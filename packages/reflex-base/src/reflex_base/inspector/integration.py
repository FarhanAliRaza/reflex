"""Coordinator between Reflex's compile pipeline and the inspector.

Other code should call into this module rather than the underlying pieces
(``capture`` / ``emit`` / ``state`` / ``shortcut`` / asset directory) so the
inspector's lifecycle has a single canonical shape:

  1. ``validate`` — fail loudly if config and runtime env disagree.
  2. ``prepare_for_compile`` — flip the runtime state flag and clear stale
     capture data at the start of each compile.
  3. ``package_json_dev_dependencies`` / ``head_components`` /
     ``plugin_text`` — declarative inputs to the compile-time templates.
  4. ``asset_source_dir`` — where browser assets live on disk; the host
     package copies them into ``.web/public``.
  5. ``write_source_map`` — emit the lookup table after pages render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from reflex_base import constants
from reflex_base.environment import environment
from reflex_base.utils.exceptions import ConfigError

from . import (
    INSPECTOR_JS_URL,
    SHORTCUT_CONFIG_KEY,
    WINDOW_CONFIG_KEY,
    capture,
    emit,
    state,
)

if TYPE_CHECKING:
    from reflex_base.components.component import Component
    from reflex_base.config import BaseConfig

LAUNCH_EDITOR_VERSION = "^2.6.1"


def is_active(config: BaseConfig) -> bool:
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


def validate(config: BaseConfig) -> None:
    """Raise if config and runtime env disagree.

    Called from ``Config._post_init`` (best effort; env may not be set yet)
    and from the compile path (env is settled). The latter is the actual
    safety net.

    Args:
        config: The current Reflex config.

    Raises:
        ConfigError: If ``frontend_inspector="dev"`` and ``REFLEX_ENV_MODE=prod``.
    """
    if (
        config.frontend_inspector == "dev"
        and environment.REFLEX_ENV_MODE.get() == constants.Env.PROD
    ):
        msg = (
            "frontend_inspector='dev' cannot be used with REFLEX_ENV_MODE=prod. "
            "Set frontend_inspector='off' for production builds."
        )
        raise ConfigError(msg)


def prepare_for_compile(config: BaseConfig) -> None:
    """Validate and sync runtime state at the start of a compile pass.

    This is the single integration point the host's compile path should
    call. After this returns, ``state.is_enabled()`` reflects the current
    build target and the registry is empty (so HMR rebuilds don't
    accumulate stale entries).

    Args:
        config: The current Reflex config.
    """
    validate(config)
    active = is_active(config)
    state.set_enabled(active)
    if active:
        capture.reset()


def package_json_dev_dependencies(config: BaseConfig) -> dict[str, str]:
    """Extra dev dependencies to merge into ``package.json``.

    Args:
        config: The current Reflex config.

    Returns:
        ``{"launch-editor": "..."}`` when active, otherwise ``{}``.
    """
    if not is_active(config):
        return {}
    return {"launch-editor": LAUNCH_EDITOR_VERSION}


def head_components(config: BaseConfig) -> list[Component]:
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
    payload = json.dumps({SHORTCUT_CONFIG_KEY: shortcut.to_json_payload()})
    return [
        Script.create(f"window.{WINDOW_CONFIG_KEY} = {payload};"),
        Script.create(type="module", src=INSPECTOR_JS_URL),
    ]


def plugin_text(config: BaseConfig) -> str:
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
