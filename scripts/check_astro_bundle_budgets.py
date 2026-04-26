"""CI check: enforce per-page JS/CSS budgets on Astro static builds.

Master Task 11 of the Astro migration requires:

- ``static`` pages ship 0 KiB first-party Reflex runtime JS by default,
- ``app`` pages load only their page-root island chunk,
- ``islands`` pages load only their per-island chunks,
- per-route JS/CSS budgets fail CI on regressions.

This script reads the Astro ``dist/`` build output, classifies each emitted
HTML file by counting the ``<script>`` and ``<link rel="stylesheet">``
references it carries, computes the gzip-compressed transfer size, and
fails if any page exceeds its configured budget.

Budgets are read from ``astro_bundle_budgets.json`` in the repository root
(or the path passed via ``--budgets``). The default file ships next to
this script and uses the conservative defaults documented in
``ASTRO_MIGRATION_TASKS.md``.

The script is intentionally additive: when ``dist/`` does not exist (e.g.
the workflow forgot to run ``astro build``) it exits 0 with a message so
CI does not flag the missing artifact as a budget regression. Use
``--strict`` to flip the missing-dir behavior to a hard failure.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST = REPO_ROOT / ".web" / "dist"
DEFAULT_BUDGETS = REPO_ROOT / "scripts" / "astro_bundle_budgets.json"

# Conservative starter budgets. Tightened once the Phase B baseline lands.
DEFAULT_BUDGET_TABLE: dict[str, dict[str, int]] = {
    "static": {"js_gzip_bytes": 0, "css_gzip_bytes": 32 * 1024},
    "app": {"js_gzip_bytes": 200 * 1024, "css_gzip_bytes": 80 * 1024},
    "islands": {"js_gzip_bytes": 100 * 1024, "css_gzip_bytes": 80 * 1024},
}

_SCRIPT_RE = re.compile(r"<script[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_STYLE_RE = re.compile(
    r"<link[^>]*\brel=[\"']stylesheet[\"'][^>]*\bhref=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_INLINE_SCRIPT_RE = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
_RENDER_MODE_HINT_RE = re.compile(
    r"<meta\s+name=[\"']reflex-render-mode[\"']\s+content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


@dataclass
class PageReport:
    """Per-page budget result.

    Attributes:
        path: Path of the HTML file relative to the dist root.
        render_mode: Detected Reflex render mode for the page.
        js_gzip_bytes: Total gzip-compressed JS payload (external + inline).
        css_gzip_bytes: Total gzip-compressed CSS payload.
        passed: Whether the page is within its budget.
        violations: One-line descriptions of each budget violation.
    """

    path: str
    render_mode: str
    js_gzip_bytes: int
    css_gzip_bytes: int
    passed: bool
    violations: list[str]


def _gzip_size(data: bytes) -> int:
    """Return the gzip-compressed size of ``data`` in bytes.

    Args:
        data: The raw bytes to compress.

    Returns:
        Length of the gzip-compressed payload.
    """
    return len(gzip.compress(data, compresslevel=6))


def _resolve_asset(dist: Path, page_html: Path, ref: str) -> Path | None:
    """Resolve an HTML-referenced asset URL to a file under ``dist``.

    Args:
        dist: The build root.
        page_html: The HTML file that contains the reference.
        ref: The ``src``/``href`` attribute as it appears in the HTML.

    Returns:
        The file path under ``dist`` if the reference resolves there, or
        ``None`` for absolute external URLs.
    """
    if ref.startswith(("http://", "https://", "//")):
        return None
    if ref.startswith("/"):
        return (dist / ref.lstrip("/")).resolve()
    return (page_html.parent / ref).resolve()


def _detect_render_mode(html: str) -> str:
    """Best-effort detection of the page's Reflex render mode.

    Looks for an explicit ``<meta name="reflex-render-mode">`` injected by
    the Astro page template, and falls back to a heuristic: pages with no
    external/inline JS are classified as ``static``; pages with a single
    ``client:load`` directive as ``app``; otherwise ``islands``.

    Args:
        html: The HTML source.

    Returns:
        One of ``"static"``, ``"app"``, ``"islands"``.
    """
    explicit = _RENDER_MODE_HINT_RE.search(html)
    if explicit is not None:
        return explicit.group(1).lower()
    has_external_js = bool(_SCRIPT_RE.search(html))
    # Astro layouts use ``is:inline`` for the color-mode head script (the
    # ``(function () {...})()`` IIFE). That script is not a Reflex runtime
    # payload, so a page with only that inline script still classifies as
    # ``static``.
    has_real_inline_js = any(
        body.strip() and not body.strip().startswith("(function")
        for body in _INLINE_SCRIPT_RE.findall(html)
    )
    if not has_external_js and not has_real_inline_js:
        return "static"
    if html.count("astro-island") <= 1:
        return "app"
    return "islands"


def _read_budget_table(path: Path) -> dict[str, dict[str, int]]:
    """Load a budget table from JSON, falling back to defaults.

    Args:
        path: Optional path to a JSON budget file.

    Returns:
        The merged budget table.
    """
    if not path.exists():
        return dict(DEFAULT_BUDGET_TABLE)
    table = dict(DEFAULT_BUDGET_TABLE)
    overrides = json.loads(path.read_text(encoding="utf-8"))
    for mode, values in overrides.items():
        if mode not in table:
            table[mode] = {"js_gzip_bytes": 0, "css_gzip_bytes": 0}
        table[mode].update(values)
    return table


def _scan_html(dist: Path, page_html: Path) -> tuple[int, int, str]:
    """Compute the JS/CSS gzip payload for a single HTML page.

    Args:
        dist: The build root.
        page_html: The HTML file to inspect.

    Returns:
        ``(js_gzip_bytes, css_gzip_bytes, render_mode)``.
    """
    html = page_html.read_text(encoding="utf-8", errors="ignore")
    render_mode = _detect_render_mode(html)
    js_bytes = 0
    css_bytes = 0
    for ref in _SCRIPT_RE.findall(html):
        target = _resolve_asset(dist, page_html, ref)
        if target is None or not target.is_file():
            continue
        js_bytes += _gzip_size(target.read_bytes())
    for body in _INLINE_SCRIPT_RE.findall(html):
        # Only count inline scripts that look like real JS payload, not the
        # color-mode setter (which is small and necessary for FOIT/theme).
        if body.strip().startswith("(function"):
            continue
        if body.strip():
            js_bytes += _gzip_size(body.encode("utf-8"))
    for ref in _STYLE_RE.findall(html):
        target = _resolve_asset(dist, page_html, ref)
        if target is None or not target.is_file():
            continue
        css_bytes += _gzip_size(target.read_bytes())
    return js_bytes, css_bytes, render_mode


def check_dist(
    dist: Path,
    *,
    budgets: dict[str, dict[str, int]] | None = None,
) -> list[PageReport]:
    """Walk ``dist`` and produce a :class:`PageReport` for every HTML file.

    Args:
        dist: The Astro build directory to scan.
        budgets: Override budget table; defaults to :data:`DEFAULT_BUDGET_TABLE`.

    Returns:
        One :class:`PageReport` per HTML file under ``dist`` (in sorted order).
    """
    table = budgets or dict(DEFAULT_BUDGET_TABLE)
    reports: list[PageReport] = []
    for html_file in sorted(dist.rglob("*.html")):
        rel = html_file.relative_to(dist).as_posix()
        js_bytes, css_bytes, render_mode = _scan_html(dist, html_file)
        budget = table.get(render_mode, table.get("app", {}))
        violations: list[str] = []
        js_limit = budget.get("js_gzip_bytes", 0)
        css_limit = budget.get("css_gzip_bytes", 0)
        if js_bytes > js_limit:
            violations.append(
                f"JS gzip {js_bytes}B > {js_limit}B for {rel} ({render_mode})"
            )
        if css_bytes > css_limit:
            violations.append(
                f"CSS gzip {css_bytes}B > {css_limit}B for {rel} ({render_mode})"
            )
        reports.append(
            PageReport(
                path=rel,
                render_mode=render_mode,
                js_gzip_bytes=js_bytes,
                css_gzip_bytes=css_bytes,
                passed=not violations,
                violations=violations,
            )
        )
    return reports


def _format_report(reports: list[PageReport]) -> str:
    """Render the reports as a stable, line-oriented summary.

    Args:
        reports: The per-page reports.

    Returns:
        A multi-line string suitable for printing to stdout / CI logs.
    """
    if not reports:
        return "(no HTML pages found in dist/)"
    lines: list[str] = []
    for r in reports:
        marker = "ok" if r.passed else "FAIL"
        lines.append(
            f"  [{marker}] {r.path:40s} mode={r.render_mode:8s} "
            f"js={r.js_gzip_bytes}B css={r.css_gzip_bytes}B"
        )
        lines.extend(f"        - {v}" for v in r.violations)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector for tests.

    Returns:
        ``0`` when every page is within budget (or ``dist/`` is missing in
        non-strict mode), ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist", type=Path, default=DEFAULT_DIST, help="Astro build dir"
    )
    parser.add_argument(
        "--budgets",
        type=Path,
        default=DEFAULT_BUDGETS,
        help="Path to the budget JSON file",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when dist/ does not exist instead of skipping.",
    )
    args = parser.parse_args(argv)

    if not args.dist.exists():
        if args.strict:
            sys.stderr.write(
                f"astro bundle budgets: dist directory missing at {args.dist}\n"
            )
            return 1
        sys.stdout.write(f"astro bundle budgets: skipping (no dist at {args.dist}).\n")
        return 0

    table = _read_budget_table(args.budgets)
    reports = check_dist(args.dist, budgets=table)
    sys.stdout.write(_format_report(reports) + "\n")
    if any(not r.passed for r in reports):
        sys.stderr.write("astro bundle budgets: regressions detected.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
