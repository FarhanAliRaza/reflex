"""Dependency-keyed persistent cache for Rust-pipeline page compiles.

Salsa-style memoization at page granularity: a page's compiled artifacts
(JSX, memo bodies, harvested imports, app-wrap components, statefulness)
are keyed by the content hashes of the source files that determine them —
the page callable's module plus everything it transitively imports inside
the project, the app's main module, and ``rxconfig.py`` — together with
the page metadata, compile mode, and Reflex version. A key hit skips page
evaluation, freeze, and emit entirely; a miss compiles and stores.

The import graph is a static ``ast`` scan, so imports invisible to static
analysis (``__import__`` with computed names, ``exec``) are not tracked,
and page output is assumed to be a deterministic function of project
source. ``REFLEX_COMPILE_CACHE=0`` disables the cache entirely.

Pages whose evaluation has side effects the cache can't replay — ones
that register new State classes or bundle dynamic libraries while
running — are detected at compile time and pinned uncacheable, so they
always evaluate (see :meth:`CompileCache.pin_uncacheable`).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import pickle
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reflex_base import constants as base_constants
from reflex_base.components.component import BaseComponent
from reflex_base.event import EventHandler, EventSpec
from reflex_base.vars.base import Var

if TYPE_CHECKING:
    from reflex.app import UnevaluatedPage

CACHE_SCHEMA = 1
_MANIFEST_NAME = "manifest.json"
_BLOBS_DIR = "blobs"


def _compiler_fingerprint() -> str:
    """Identity of the native compiler build, for manifest invalidation.

    Emitter changes alter output for unchanged sources, so a rebuilt
    extension must invalidate every cached page. A stat fingerprint is
    enough — maturin rewrites the shared object on every build.

    Returns:
        An opaque token that changes whenever the extension is rebuilt.
    """
    spec = importlib.util.find_spec("reflex_compiler_rust._native")
    if spec is None or spec.origin is None:
        return "no-native"
    st = Path(spec.origin).stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _stable_token(obj: Any) -> str | None:
    """Serialize a page-metadata value into a deterministic string.

    Used to fold ``UnevaluatedPage`` metadata (title, meta tags, on_load,
    context) into the cache key. Values without a stable serialization
    (address-bearing reprs, arbitrary objects) return ``None``, which
    makes the page uncacheable rather than risking a false hit.

    Args:
        obj: The metadata value to serialize.

    Returns:
        A deterministic token, or ``None`` if none exists for this value.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return repr(obj)
    if isinstance(obj, Var):
        return f"var:{obj!s}"
    if isinstance(obj, EventHandler):
        fn = obj.fn
        return f"handler:{fn.__module__}.{fn.__qualname__}"
    if isinstance(obj, EventSpec):
        parts = [_stable_token(obj.handler)]
        parts.extend(_stable_token(arg) for pair in obj.args for arg in pair)
        if any(p is None for p in parts):
            return None
        return f"spec:({','.join(p for p in parts if p is not None)})"
    if isinstance(obj, BaseComponent):
        return None
    if isinstance(obj, (list, tuple)):
        tokens = [_stable_token(item) for item in obj]
        if any(t is None for t in tokens):
            return None
        return f"[{','.join(t for t in tokens if t is not None)}]"
    if isinstance(obj, Mapping):
        items = [(_stable_token(k), _stable_token(v)) for k, v in obj.items()]
        if any(k is None or v is None for k, v in items):
            return None
        return f"{{{','.join(f'{k}:{v}' for k, v in sorted(items))}}}"
    if callable(obj):
        module = getattr(obj, "__module__", None)
        qualname = getattr(obj, "__qualname__", None)
        if module and qualname:
            return f"fn:{module}.{qualname}"
    return None


class CompileCache:
    """Persistent page-compile cache keyed by source-file dependency hashes.

    One instance per compile run. ``key_for`` computes the input key for a
    route (or ``None`` when the page isn't cacheable), ``lookup``/``put``
    move entries through the on-disk store, and ``save`` flushes the
    manifest and prunes orphaned blobs.
    """

    def __init__(
        self,
        project_root: Path,
        cache_dir: Path,
        base_dep_files: list[Path],
        mode_token: str = "",
    ) -> None:
        """Create a cache rooted at a project directory.

        Args:
            project_root: Directory below which source files are tracked;
                imports resolving outside it are ignored.
            cache_dir: Directory holding the manifest and entry blobs.
            base_dep_files: Files folded into every page's dependency
                closure (the app's main module, ``rxconfig.py``) so
                app-level inputs like theme/style invalidate all pages.
            mode_token: Discriminator mixed into every key for inputs
                outside the file graph (e.g. ``"prod"``/``"dev"``).
        """
        self.root = project_root.resolve()
        self.dir = cache_dir
        self._base_dep_files = base_dep_files
        self._mode_token = mode_token
        self._dirty = False
        # files: rel path -> {"mt": mtime_ns, "sz": size, "sha": hex, "deps": [rel...]}
        # pages: route -> {"key": hex, "ok": bool}  (ok=False pins uncacheable)
        self._files: dict[str, dict[str, Any]] = {}
        self._pages: dict[str, dict[str, Any]] = {}
        manifest_path = self.dir / _MANIFEST_NAME
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError):
                manifest = None
            if (
                manifest is not None
                and manifest.get("schema") == CACHE_SCHEMA
                and manifest.get("version") == base_constants.Reflex.VERSION
                and manifest.get("compiler") == _compiler_fingerprint()
            ):
                self._files = manifest.get("files", {})
                self._pages = manifest.get("pages", {})

    @classmethod
    def default(cls, mode_token: str) -> CompileCache | None:
        """Build the standard cache for the current project, if possible.

        Args:
            mode_token: Discriminator mixed into every key for inputs that
                live outside the file graph (e.g. ``"prod"``/``"dev"``).

        Returns:
            A ready cache, or ``None`` when caching is disabled via
            ``REFLEX_COMPILE_CACHE=0`` or the app's main module can't be
            resolved to a project file (synthetic / in-memory apps).
        """
        if os.environ.get("REFLEX_COMPILE_CACHE", "1") == "0":
            return None
        # Inline imports: reflex.utils.prerequisites pulls in reflex.config
        # and would be circular at reflex.compiler import time (same reason
        # rust_pipeline imports it inside functions).
        from reflex_base.config import get_config

        from reflex.utils.prerequisites import get_web_dir

        app_name = get_config().app_name
        main_module = sys.modules.get(f"{app_name}.{app_name}") or sys.modules.get(
            app_name
        )
        main_file = getattr(main_module, "__file__", None)
        if not main_file:
            return None
        root = Path.cwd()
        main_path = Path(main_file).resolve()
        if not main_path.is_relative_to(root):
            return None
        base_deps = [main_path]
        rxconfig = root / base_constants.Config.FILE
        if rxconfig.is_file():
            base_deps.append(rxconfig)
        return cls(root, Path(get_web_dir()) / ".rxcache", base_deps, mode_token)

    def key_for(self, route: str, unevaluated_page: UnevaluatedPage) -> str | None:
        """Compute the input key for a route, or ``None`` if uncacheable.

        A page is cacheable when its component is a callable defined in a
        file under the project root and all its metadata has a stable
        serialization.

        Args:
            route: The normalized route being compiled.
            unevaluated_page: The registered page record.

        Returns:
            A hex digest key, or ``None`` when the page can't be cached.
        """
        page = unevaluated_page.component
        if isinstance(page, BaseComponent) or not callable(page):
            return None
        module = sys.modules.get(getattr(page, "__module__", "") or "")
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            return None
        page_path = Path(module_file).resolve()
        if not page_path.is_relative_to(self.root):
            return None
        meta_token = _stable_token((
            unevaluated_page.title,
            unevaluated_page.description,
            unevaluated_page.image,
            unevaluated_page.meta,
            unevaluated_page.on_load,
            unevaluated_page.context,
        ))
        if meta_token is None:
            return None
        closure = self._closure([page_path, *self._base_dep_files])
        if closure is None:
            return None
        payload = json.dumps(
            [self._mode_token, route, meta_token, sorted(closure.items())],
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def lookup(self, route: str, key: str) -> dict[str, Any] | None:
        """Fetch the stored entry for a route if its key still matches.

        Args:
            route: The normalized route.
            key: The key from :meth:`key_for` for the current inputs.

        Returns:
            The stored entry dict (``page_js``, ``memo_bodies``,
            ``imports``, ``app_wraps``, ``stateful``) or ``None`` on miss,
            key mismatch, pinned-uncacheable route, or unreadable blob.
        """
        record = self._pages.get(route)
        if not record or not record.get("ok") or record.get("key") != key:
            return None
        blob_path = self.dir / _BLOBS_DIR / f"{key}.pkl"
        # IO boundary: a missing/corrupt/unimportable blob is a cache miss,
        # not an error — the page just recompiles and overwrites it.
        try:
            entry = pickle.loads(blob_path.read_bytes())
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError):
            return None
        return entry

    def put(self, route: str, key: str, entry: dict[str, Any]) -> None:
        """Store a compiled page's artifacts under its input key.

        Routes pinned uncacheable are never stored. A page whose artifacts
        cannot pickle (e.g. an app-wrap component class defined inside a
        method, like DataEditor's Portal) is pinned uncacheable instead —
        it recompiles every build rather than failing it.

        Args:
            route: The normalized route.
            key: The key from :meth:`key_for` for the inputs just compiled.
            entry: Artifact dict.
        """
        record = self._pages.get(route)
        if record is not None and not record.get("ok", True):
            return
        try:
            payload = pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL)
        except (pickle.PicklingError, TypeError, AttributeError):
            self.pin_uncacheable(route)
            return
        blobs = self.dir / _BLOBS_DIR
        blobs.mkdir(parents=True, exist_ok=True)
        tmp = blobs / f".{key}.tmp"
        tmp.write_bytes(payload)
        tmp.replace(blobs / f"{key}.pkl")
        self._pages[route] = {"key": key, "ok": True}
        self._dirty = True

    def pin_uncacheable(self, route: str) -> None:
        """Permanently exclude a route from caching.

        Called when compiling the route had side effects a cache hit could
        not replay (registered State classes, bundled dynamic libraries).
        The pin is sticky across key changes because side-effect detection
        is only reliable the first time the page runs in a process.

        Args:
            route: The normalized route to pin.
        """
        self._pages[route] = {"ok": False}
        self._dirty = True

    def save(self) -> None:
        """Flush the manifest and prune blobs no live entry references."""
        if not self._dirty:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        live_keys = {
            record["key"] for record in self._pages.values() if record.get("ok")
        }
        blobs = self.dir / _BLOBS_DIR
        if blobs.is_dir():
            for blob in blobs.glob("*.pkl"):
                if blob.stem not in live_keys:
                    blob.unlink(missing_ok=True)
        manifest = {
            "schema": CACHE_SCHEMA,
            "version": base_constants.Reflex.VERSION,
            "compiler": _compiler_fingerprint(),
            "files": self._files,
            "pages": self._pages,
        }
        tmp = self.dir / f".{_MANIFEST_NAME}.tmp"
        tmp.write_text(json.dumps(manifest, separators=(",", ":")))
        tmp.replace(self.dir / _MANIFEST_NAME)
        self._dirty = False

    def _file_record(self, path: Path) -> dict[str, Any] | None:
        """Hash + dependency-scan a file, memoized on (mtime, size).

        Args:
            path: Absolute path under the project root.

        Returns:
            The record dict, or ``None`` if the file can't be read.
        """
        rel = str(path.relative_to(self.root))
        try:
            stat = path.stat()
        except OSError:
            return None
        record = self._files.get(rel)
        if (
            record is not None
            and record["mt"] == stat.st_mtime_ns
            and record["sz"] == stat.st_size
        ):
            return record
        try:
            source = path.read_bytes()
        except OSError:
            return None
        record = {
            "mt": stat.st_mtime_ns,
            "sz": stat.st_size,
            "sha": hashlib.sha256(source).hexdigest(),
            "deps": self._scan_deps(path, source),
        }
        self._files[rel] = record
        self._dirty = True
        return record

    def _scan_deps(self, path: Path, source: bytes) -> list[str]:
        """Statically resolve a file's project-local imports.

        ``ast.walk`` sees imports at any nesting depth (module level,
        function bodies, conditionals); only computed/``exec`` imports
        are invisible.

        Args:
            path: The file being scanned (anchors relative imports).
            source: Its raw contents.

        Returns:
            Sorted unique project-relative paths of imported files.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Mid-edit file: content hash still changes the key, and the
            # page would fail to import anyway.
            return []
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.update(self._resolve_module(alias.name.split("."), self.root))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    if not base.is_relative_to(self.root):
                        continue
                else:
                    base = self.root
                parts = node.module.split(".") if node.module else []
                deps.update(self._resolve_module(parts, base))
                # `from pkg import name` may bind submodules, not attrs.
                package_dir = base.joinpath(*parts) if parts else base
                if package_dir.is_dir():
                    for alias in node.names:
                        deps.update(self._resolve_module([alias.name], package_dir))
        return sorted(deps)

    def _resolve_module(self, parts: list[str], base: Path) -> list[str]:
        """Resolve dotted module parts to project-relative file paths.

        Walks packages cumulatively (importing ``a.b.c`` executes ``a``
        and ``a.b`` too, so their ``__init__.py`` files are dependencies).
        Anything that doesn't resolve under the project root (stdlib,
        site-packages) yields nothing.

        Args:
            parts: Dotted module path, split.
            base: Directory the first part is resolved against.

        Returns:
            Project-relative paths of every file the import executes.
        """
        out: list[str] = []
        current = base
        for part in parts:
            package_init = current / part / "__init__.py"
            module_file = current / f"{part}.py"
            if package_init.is_file():
                out.append(str(package_init.relative_to(self.root)))
                current = current / part
            elif module_file.is_file():
                out.append(str(module_file.relative_to(self.root)))
                break
            else:
                break
        return out

    def _closure(self, seeds: list[Path]) -> dict[str, str] | None:
        """Transitive dependency closure as ``{rel path: content sha}``.

        Args:
            seeds: Absolute file paths to start from.

        Returns:
            The closure mapping, or ``None`` when a seed is unreadable
            (making the page uncacheable).
        """
        closure: dict[str, str] = {}
        queue: list[str] = []
        for seed in seeds:
            rel = str(seed.relative_to(self.root))
            record = self._file_record(seed)
            if record is None:
                return None
            closure[rel] = record["sha"]
            queue.extend(record["deps"])
        # Non-seed deps that vanished just drop out of the closure — the
        # importing file's content (and so the key) changed with them.
        while queue:
            rel = queue.pop()
            if rel in closure:
                continue
            record = self._file_record(self.root / rel)
            if record is None:
                continue
            closure[rel] = record["sha"]
            queue.extend(d for d in record["deps"] if d not in closure)
        return closure
