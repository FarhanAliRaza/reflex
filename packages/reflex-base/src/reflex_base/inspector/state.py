"""Global toggle for the frontend inspector.

A single boolean module-level flag is the source of truth. ``Config`` flips it
during ``_post_init`` so it is set before the user's app module imports.
"""

from __future__ import annotations

_ENABLED: bool = False


def set_enabled(on: bool) -> None:
    """Set whether the inspector is active.

    Args:
        on: True to enable, False to disable.
    """
    global _ENABLED
    _ENABLED = bool(on)


def is_enabled() -> bool:
    """Return whether the inspector is currently active.

    Returns:
        True if the inspector should capture call sites and emit ``data-rx``.
    """
    return _ENABLED
