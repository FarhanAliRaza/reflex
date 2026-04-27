"""Walk the Python call stack and record where a component was created."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import itertools
import sys
from pathlib import Path

from . import state


@dataclasses.dataclass(frozen=True, slots=True)
class SourceInfo:
    """A user-code frame that constructed a component."""

    file: str
    line: int
    column: int
    component: str


_REGISTRY: dict[int, SourceInfo] = {}
_COUNTER = itertools.count(1)


_FRAMEWORK_PACKAGE_PREFIXES: tuple[str, ...] = (
    "reflex",
    "reflex_base",
    "reflex_components_",
)


def _is_framework_package(name: str) -> bool:
    """Whether a top-level package name is part of the Reflex framework.

    Args:
        name: A top-level package name as it would appear in ``sys.modules``.

    Returns:
        True for ``reflex``/``reflex_base`` and any ``reflex_components_*``
        distribution; False for anything else.
    """
    if name in ("reflex", "reflex_base"):
        return True
    return name.startswith("reflex_components_")


def _discover_framework_roots() -> tuple[Path, ...]:
    """Find directories whose frames must be skipped during stack walking.

    The discovery walks both already-imported modules in ``sys.modules`` and
    the installed distributions reported by :mod:`importlib.metadata`. A
    module whose package name passes :func:`_is_framework_package` is
    included regardless of how the user installed it (editable, wheel, src
    layout).

    Returns:
        Resolved, deduplicated paths to every framework package directory.
    """
    roots: list[Path] = []

    for name in ("reflex", "reflex_base"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        file = getattr(module, "__file__", None)
        if file is not None:
            roots.append(Path(file).parent.resolve())

    for name, module in list(sys.modules.items()):
        if "." in name or not _is_framework_package(name):
            continue
        file = getattr(module, "__file__", None)
        if file is None:
            continue
        roots.append(Path(file).parent.resolve())

    try:
        distributions = list(importlib.metadata.distributions())
    except Exception:
        distributions = []

    for dist in distributions:
        try:
            top_level = (dist.read_text("top_level.txt") or "").splitlines()
        except Exception:
            top_level = []
        for raw in top_level:
            top = raw.strip()
            if not top or not _is_framework_package(top):
                continue
            try:
                pkg = importlib.import_module(top)
            except Exception:
                continue
            file = getattr(pkg, "__file__", None)
            if file is not None:
                roots.append(Path(file).parent.resolve())

    return tuple(dict.fromkeys(roots))


_FRAMEWORK_ROOTS: tuple[Path, ...] = _discover_framework_roots()
# Snapshot of ``len(sys.modules)`` taken at the time of the last scan. A
# cheap heuristic for "have any new modules been imported since?" without
# having to iterate ``sys.modules`` on every component creation.
_SYS_MODULES_LEN: int = len(sys.modules)


def refresh_framework_roots() -> tuple[Path, ...]:
    """Re-scan ``sys.modules`` and rebuild the cached framework roots.

    Useful when a framework sub-package is imported lazily after the
    inspector has already initialised.

    Returns:
        The freshly discovered framework roots.
    """
    global _FRAMEWORK_ROOTS, _SYS_MODULES_LEN
    _FRAMEWORK_ROOTS = _discover_framework_roots()
    _SYS_MODULES_LEN = len(sys.modules)
    return _FRAMEWORK_ROOTS


def _maybe_refresh_framework_roots() -> None:
    """Cheaply refresh the cache when ``sys.modules`` has grown.

    The rescan only walks framework-prefixed top-level packages, so it is
    O(n) over the small subset of Reflex packages even if ``sys.modules``
    is large.
    """
    if len(sys.modules) != _SYS_MODULES_LEN:
        refresh_framework_roots()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_framework_frame(filename: str) -> bool:
    """Return whether the given filename belongs to the framework itself.

    Args:
        filename: The frame's ``co_filename``.

    Returns:
        True if the frame is internal (and should be skipped while walking).
    """
    try:
        path = Path(filename).resolve()
    except OSError:
        return True
    return any(_is_relative_to(path, root) for root in _FRAMEWORK_ROOTS)


def capture(component_name: str) -> int | None:
    """Walk the call stack and return a fresh inspector id for the user frame.

    Args:
        component_name: ``cls.__name__`` of the component being constructed.

    Returns:
        A new integer id when the inspector is enabled and a non-framework
        frame is found; ``None`` otherwise (e.g. inspector disabled, only
        framework code on the stack).
    """
    if not state.is_enabled():
        return None
    _maybe_refresh_framework_roots()
    frame = sys._getframe(1)
    while frame is not None:
        if not _is_framework_frame(frame.f_code.co_filename):
            cid = next(_COUNTER)
            _REGISTRY[cid] = SourceInfo(
                file=str(Path(frame.f_code.co_filename).resolve()),
                line=frame.f_lineno,
                column=1,
                component=component_name,
            )
            return cid
        frame = frame.f_back
    return None


def snapshot() -> dict[int, SourceInfo]:
    """Return a copy of the current registry.

    Returns:
        A shallow copy of the inspector id → ``SourceInfo`` mapping.
    """
    return dict(_REGISTRY)


def reset() -> None:
    """Clear the registry. Intended for tests."""
    global _COUNTER
    _REGISTRY.clear()
    _COUNTER = itertools.count(1)
