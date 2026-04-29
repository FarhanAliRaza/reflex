"""The pyi generator module.

The last commit that touched ``pyi_hashes.json`` is used as the baseline of
"last successful regeneration". Sources changed since that commit (committed,
staged, unstaged, untracked) drive an incremental run; the change set is
expanded along the import graph so modifying a parent class also regenerates
the stubs of every subclass that inherits from it.

A full regeneration is forced when ``pyi_hashes.json`` is absent, or when the
generator's own files (``scripts/make_pyi.py`` or the ``PyiGenerator``
library) appear in the change set.
"""

import ast
import logging
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from reflex_base.utils.pyi_generator import PyiGenerator

logger = logging.getLogger("pyi_generator")

PYI_HASHES = Path("pyi_hashes.json")
GENERATOR_PATHS = frozenset({
    "scripts/make_pyi.py",
    "packages/reflex-base/src/reflex_base/utils/pyi_generator.py",
})

DEFAULT_TARGETS = [
    "reflex/components",
    "reflex/experimental",
    "reflex/__init__.py",
    "packages/reflex-components-code/src/reflex_components_code",
    "packages/reflex-components-core/src/reflex_components_core",
    "packages/reflex-components-dataeditor/src/reflex_components_dataeditor",
    "packages/reflex-components-gridjs/src/reflex_components_gridjs",
    "packages/reflex-components-lucide/src/reflex_components_lucide",
    "packages/reflex-components-markdown/src/reflex_components_markdown",
    "packages/reflex-components-moment/src/reflex_components_moment",
    "packages/reflex-components-plotly/src/reflex_components_plotly",
    "packages/reflex-components-radix/src/reflex_components_radix",
    "packages/reflex-components-react-player/src/reflex_components_react_player",
    "packages/reflex-components-recharts/src/reflex_components_recharts",
    "packages/reflex-components-sonner/src/reflex_components_sonner",
]


def _git(*args: str) -> list[str]:
    """Run ``git`` with `args` and return non-empty stdout lines.

    Args:
        *args: Arguments forwarded to ``git``.

    Returns:
        Non-empty lines of standard output, with trailing newlines stripped.
    """
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return [line for line in result.stdout.splitlines() if line]


def _last_regen_sha() -> str | None:
    """Return the SHA of the last commit that touched ``pyi_hashes.json``.

    Returns:
        The commit SHA, or ``None`` if the file is missing or has no history.
    """
    if not PYI_HASHES.exists():
        return None
    out = _git("log", "-1", "--format=%H", "--", str(PYI_HASHES))
    return out[0] if out else None


def _changed_python_paths(sha: str) -> set[str]:
    """All ``.py`` paths changed since `sha`.

    A single ``git diff <sha>`` covers committed, staged, and unstaged changes
    (it diffs the working tree against the commit). Brand-new untracked files
    aren't included; ``git add`` them first to bring them into scope.

    Args:
        sha: The baseline commit SHA.

    Returns:
        Repo-relative paths of every ``.py`` file changed since `sha`.
    """
    return {p for p in _git("diff", "--name-only", sha) if p.endswith(".py")}


def _key(path: Path) -> str:
    """POSIX-style repo-relative string key for `path`.

    Args:
        path: The absolute path to convert.

    Returns:
        Repo-relative POSIX path string.
    """
    return path.relative_to(Path.cwd()).as_posix()


def _gather_sources(targets: list[str]) -> list[Path]:
    """Resolve every ``.py`` file reachable from `targets`.

    Args:
        targets: User-provided target list (files or directories).

    Returns:
        Sorted list of absolute paths to ``.py`` files under `targets`.
    """
    seen: set[Path] = set()
    for target in targets:
        p = Path(target).resolve()
        if p.is_file() and p.suffix == ".py":
            seen.add(p)
        elif p.is_dir():
            seen.update(p.rglob("*.py"))
    return sorted(seen)


def _package_parts(path: Path) -> list[str]:
    """Dotted parts of the package containing `path`.

    For ``pkg/foo/bar.py`` and for ``pkg/foo/__init__.py`` this returns
    ``["pkg", "foo"]`` — i.e. the package the module participates in, not the
    module itself.

    Args:
        path: Absolute path to a ``.py`` file.

    Returns:
        Package parts in import order (top-level first), or ``[]`` if `path`
        is not inside a package.
    """
    parts: list[str] = []
    parent = path.parent
    while (parent / "__init__.py").exists() and parent != parent.parent:
        parts.append(parent.name)
        parent = parent.parent
    return list(reversed(parts))


def _module_aliases(path: Path) -> set[str]:
    """Dotted module names that an ``import`` could resolve to `path`.

    Walks upward while parent directories contain ``__init__.py`` to recover
    the top-level package. For ``__init__.py`` files, also emits the package
    name on its own (``import pkg`` reaches ``pkg/__init__.py``).

    Args:
        path: Absolute path to a ``.py`` file.

    Returns:
        Set of dotted module names that could refer to `path`.
    """
    pkg = _package_parts(path)
    if path.stem == "__init__":
        full = ".".join([*pkg, "__init__"])
        aliases = {full}
        if pkg:
            aliases.add(".".join(pkg))
        return aliases
    return {".".join([*pkg, path.stem])} if pkg else {path.stem}


def _iter_import_nodes(
    nodes: Iterable[ast.AST],
) -> Iterable[ast.Import | ast.ImportFrom]:
    """Yield import nodes reachable without entering function or class bodies.

    Imports live at module top level or inside ``if TYPE_CHECKING:`` /
    ``try/except ImportError`` / ``with`` blocks. Walking function and class
    bodies wastes time and never finds anything that shapes the import graph.

    Args:
        nodes: AST nodes to scan (typically ``tree.body``).

    Yields:
        Each ``ast.Import`` / ``ast.ImportFrom`` node encountered.
    """
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            yield from _iter_import_nodes(node.body)
            yield from _iter_import_nodes(node.orelse)
        elif isinstance(node, ast.Try):
            yield from _iter_import_nodes(node.body)
            yield from _iter_import_nodes(node.orelse)
            yield from _iter_import_nodes(node.finalbody)
            for handler in node.handlers:
                yield from _iter_import_nodes(handler.body)
        elif hasattr(ast, "TryStar") and isinstance(node, ast.TryStar):
            yield from _iter_import_nodes(node.body)
            for handler in node.handlers:
                yield from _iter_import_nodes(handler.body)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from _iter_import_nodes(node.body)


def _imports_in(path: Path) -> set[str]:
    """Absolute module names imported by `path`.

    For ``from pkg import name`` we emit both ``pkg`` and ``pkg.name`` so the
    graph captures dependencies on either the package or one of its submodules.
    Relative imports (``from .base import X``, ``from ..util import Y``) are
    resolved against `path`'s own package so they participate in the graph.

    Args:
        path: Absolute path to a ``.py`` file.

    Returns:
        Dotted module names referenced by imports in `path`.
    """
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    imports: set[str] = set()
    pkg = _package_parts(path)
    for node in _iter_import_nodes(tree.body):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
            continue
        if node.level == 0:
            if node.module:
                imports.add(node.module)
                imports.update(f"{node.module}.{alias.name}" for alias in node.names)
            continue
        if node.level > len(pkg):
            continue
        base = pkg[: len(pkg) - (node.level - 1)]
        if not base:
            continue
        target = ".".join([*base, node.module]) if node.module else ".".join(base)
        imports.add(target)
        imports.update(f"{target}.{alias.name}" for alias in node.names)
    return imports


def _expand_with_dependents(changed: set[Path], sources: list[Path]) -> set[Path]:
    """Add every source that transitively imports a changed source.

    Args:
        changed: Sources detected as directly modified.
        sources: All sources reachable from the targets.

    Returns:
        `changed` union all sources whose import graph reaches a changed source.
    """
    importers: dict[str, set[Path]] = defaultdict(set)
    for src in sources:
        for mod in _imports_in(src):
            importers[mod].add(src)

    seen = set(changed)
    queue = list(changed)
    while queue:
        current = queue.pop()
        for alias in _module_aliases(current):
            for dependent in importers.get(alias, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    queue.append(dependent)
    return seen


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("blib2to3.pgen2.driver").setLevel(logging.INFO)

    targets = (
        [arg for arg in sys.argv[1:] if not arg.startswith("tests")]
        if len(sys.argv) > 1
        else DEFAULT_TARGETS
    )
    targets = [
        target
        for target in targets
        if any(str(target).startswith(prefix) for prefix in DEFAULT_TARGETS)
    ]

    logger.info(f"Running .pyi generator for {targets}")

    sha = _last_regen_sha()
    if sha is None:
        if PYI_HASHES.exists():
            logger.warning(
                f"{PYI_HASHES} exists locally but has no git history; "
                "every run will full-regenerate until the file is committed."
            )
        else:
            logger.info(
                "No pyi_hashes.json baseline in git, regenerating all .pyi files"
            )
        changed_files: list[Path] | None = None
    else:
        changed = _changed_python_paths(sha)
        if changed & GENERATOR_PATHS:
            logger.info("Generator changed, regenerating all .pyi files")
            changed_files = None
        else:
            sources = _gather_sources(targets)
            sources_by_key = {_key(p): p for p in sources}
            directly_changed = {
                sources_by_key[p] for p in changed if p in sources_by_key
            }
            if not directly_changed:
                logger.info("No source files changed since last regeneration")
                changed_files = []
            else:
                expanded = _expand_with_dependents(directly_changed, sources)
                logger.info(
                    f"Detected {len(directly_changed)} direct change(s), "
                    f"{len(expanded)} after transitive expansion"
                )
                changed_files = [Path(_key(p)) for p in expanded]

    gen = PyiGenerator()
    gen.scan_all(targets, changed_files, use_json=True)
