"""CI check: react-router references must stay inside target-specific surfaces.

Master Task 1 of the Astro migration enumerates the four React-Router-hardcoded
surfaces that must become target-aware. Every other module under
`packages/reflex-base/src/reflex_base/` and `reflex/` should be free of direct
`react-router` / `@react-router/*` references after the refactor.

This script greps the source tree, subtracts the allow-listed locations, and
exits non-zero if anything else mentions React Router. It is intentionally
narrow: docs strings that mention the React Router target by name are fine,
but actual JS/TS imports and Python constants tied to the package name are not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Target-specific files that are allowed to reference React Router. These match
# the "four React-Router-hardcoded surfaces" enumerated in
# ASTRO_MIGRATION_TASKS.md (Master Task 1) plus the React-Router-only generated
# template files under .templates/web/app/.
ALLOW_LIST: frozenset[str] = frozenset({
    # React Router target client entry. Not emitted on the Astro target.
    "packages/reflex-base/src/reflex_base/.templates/web/app/entry.client.js",
    # React Router target routes manifest. Not emitted on the Astro target.
    "packages/reflex-base/src/reflex_base/.templates/web/app/routes.js",
    # Root template emits Outlet for React Router; Astro emits a different
    # root template entirely.
    "packages/reflex-base/src/reflex_base/compiler/templates.py",
    # Per-target router adapter generator. The React Router branch imports
    # ``react-router`` hooks; the Astro branch uses ``window.location``.
    "packages/reflex-base/src/reflex_base/compiler/router_adapter_template.py",
    # Target-aware command/dependency table (this is exactly the place
    # React Router constants are supposed to live).
    "packages/reflex-base/src/reflex_base/constants/installer.py",
    # Target-aware constants module (CONFIG_FILE etc. for each target).
    "packages/reflex-base/src/reflex_base/constants/base.py",
    # The Reflex Plugin shipped with the project that targets React
    # Router specifically.
    "packages/reflex-base/src/reflex_base/plugins/sitemap.py",
    # The CI-check script itself.
    "scripts/check_react_router_isolation.py",
})

# Patterns that count as a "real" React Router reference. Comments and
# documentation that just mention the React Router target by name are fine.
PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""['\"]react-router['\"]"""),
    re.compile(r"""['\"]react-router-dom['\"]"""),
    re.compile(r"""['\"]@react-router/"""),
    re.compile(r"""from\s+['\"]react-router"""),
    re.compile(r"""require\(\s*['\"]react-router"""),
)

SEARCH_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "reflex",
    REPO_ROOT / "packages" / "reflex-base" / "src",
)


def _iter_source_files() -> list[Path]:
    """Walk the search roots and yield every .py / .js / .ts file.

    Returns:
        A sorted list of source files to scan.
    """
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}:
                continue
            files.append(path)
    return sorted(files)


def main() -> int:
    """Run the React Router isolation check.

    Returns:
        0 if the source tree is clean, 1 otherwise.
    """
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_source_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOW_LIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in PATTERNS:
                if pattern.search(line):
                    offenders.append((path, lineno, line.rstrip()))
                    break
    if offenders:
        sys.stderr.write(
            "react-router references found outside target-specific surfaces:\n"
        )
        for path, lineno, line in offenders:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sys.stderr.write(f"  {rel}:{lineno}: {line}\n")
        sys.stderr.write(
            "\nIf the location is target-specific, add it to ALLOW_LIST in "
            "scripts/check_react_router_isolation.py.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
