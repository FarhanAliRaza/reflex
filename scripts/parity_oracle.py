"""Byte-parity oracle for Rust-pipeline perf work.

Full design + justification of every canonicalization rule lives in
``PARITY_ORACLE.md`` at the repo root — read that before changing what this
script captures or how it compares.

Captured surface (per case): ``page_js`` bytes, memo bodies (sorted by name),
the harvested import dict (canonicalized), and ``snapshot_stats`` (a coarse
intermediate-state check on the frozen arena). Cases cover the codegen corpus,
both heavy benchmark pages, a page compiled with every optional kwarg, and the
three root artifacts that also freeze Component trees (``_document.js``,
``theme.js``, ``root.jsx``).

Usage::

    uv run python scripts/parity_oracle.py capture          # write the golden
    uv run python scripts/parity_oracle.py check             # diff vs golden (exit 1 on drift)

Golden path defaults to ``tests/codegen_corpus/parity_golden.json`` (in-repo —
a ``/tmp`` golden was lost to a tmpfs wipe once; never again). Override with a
third arg. ``capture`` is the baseline taken BEFORE a change; ``check`` is run
AFTER each step and must report zero drift.
"""

from __future__ import annotations

# Python 3.14 / pydantic compat shim — must precede any reflex import.
import inspect as _inspect
import typing as _typing

_orig_eval_type = _typing._eval_type
_params = _inspect.signature(_orig_eval_type).parameters
if "prefer_fwd_module" not in _params:

    def _eval_type_compat(*args, **kwargs):
        return _orig_eval_type(
            *args, **{k: v for k, v in kwargs.items() if k in _params}
        )

    _typing._eval_type = _eval_type_compat  # type: ignore[assignment]

import json
import sys
from pathlib import Path
from typing import Any, Callable

DEFAULT_GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "codegen_corpus"
    / "parity_golden.json"
)


_IMPORT_FIELDS = ("tag", "alias", "is_default", "install", "render", "package_path")


def _canon_entry(entry: Any) -> str:
    """Serialize one import entry by its fields, stable across processes.

    Both Python ``ImportVar`` and the native ``RustImportVar`` expose the
    same field surface; ``repr`` is unusable because ``RustImportVar`` falls
    back to an address-bearing default repr.
    """
    return repr(tuple(getattr(entry, f, None) for f in _IMPORT_FIELDS))


def _canon_imports(imports: dict[str, list]) -> dict[str, list[str]]:
    """Canonicalize the harvested import dict into a stable, diffable shape.

    Keys sorted; each module's entries serialized by field, deduped, and
    sorted. Multiplicity of identical entries is deliberately NOT compared:
    the harvest accumulates one entry per contributing node and every
    consumer (the emit's import lines — already covered byte-exactly by
    ``page_js`` — and ``_get_frontend_packages``) dedups, so duplicate
    counts depend on walk internals (e.g. VarData object identity), not on
    output semantics.
    """
    return {
        module: sorted({_canon_entry(entry) for entry in (entries or [])})
        for module, entries in sorted(imports.items())
    }


def _build_cases() -> list[tuple[str, str, str, Callable[[], Any]]]:
    """Return ``(name, ident, route, build)`` for every parity case.

    Combines the codegen corpus fixtures with the two heavy benchmark pages
    (which exercise nested foreach / match / state / events end-to-end).
    """
    from tests.codegen_corpus._runner import discover

    cases: list[tuple[str, str, str, Callable[[], Any]]] = []
    for fx in discover():
        cases.append((f"corpus:{fx.name}", fx.ident, fx.route, fx.build))

    from tests.benchmarks.fixtures import _complicated_page, _stateful_page

    cases.append(("bench:complicated", "Complicated", "/complicated", _complicated_page))
    cases.append(("bench:stateful", "Stateful", "/stateful", _stateful_page))
    return cases


def _capture_root_artifacts(sess: Any) -> dict[str, Any]:
    """Capture the non-page artifacts that freeze Component trees.

    ``_document.js``, ``theme.js``, and ``root.jsx`` go through the same
    ``freeze.rs`` walk as pages, so a freeze refactor can break them while
    every page case stays byte-identical. Inputs mirror the production
    call sites in ``rust_pipeline._emit_static_artifacts`` /
    ``compile_pages``. The pure string-template artifacts (context.js,
    styles.css, stateful_pages.json) take no Component input and are
    deliberately not captured.
    """
    import tempfile

    import reflex as rx

    from reflex.compiler.utils import create_theme

    out: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as td:
        doc_path = str(Path(td) / "_document.js")
        sess.compile_document_root_arena(
            head_components=[],
            html_lang="en",
            html_custom_attrs={"suppressHydrationWarning": True},
            out_path=doc_path,
        )
        out["root:document"] = {"file_js": Path(doc_path).read_text()}

        theme_path = str(Path(td) / "theme.js")
        theme = create_theme(
            {
                "font_family": "Inter",
                "::selection": {"background_color": "lightgray"},
                "a": {"color": "blue", "_hover": {"color": "red"}},
            }
        )
        sess.compile_theme_from_component_arena(theme, theme_path)
        out["root:theme"] = {"file_js": Path(theme_path).read_text()}

        root_path = str(Path(td) / "root.jsx")
        app_root = rx.fragment(rx.box(rx.text("parity root")))
        imports = sess.compile_app_root_arena(
            app_root,
            'import * as __reflex_lib0 from "$/public/lib0.js";',
            '    "$/public/lib0.js": __reflex_lib0,',
            root_path,
        )
        out["root:app"] = {
            "file_js": Path(root_path).read_text(),
            "imports": _canon_imports(imports),
        }
    return out


def _capture_all() -> dict[str, Any]:
    from reflex.compiler.session import CompilerSession

    sess = CompilerSession()
    out: dict[str, Any] = {}
    page_kwargs_case: tuple[str, str, Callable[[], Any]] | None = None
    for name, ident, route, build in _build_cases():
        component = build()
        page_js, bodies, imports, *_ = sess.compile_page_from_component_arena(
            component, ident, route
        )
        out[name] = {
            "page_js": page_js,
            # Lists (not tuples) so a captured snapshot compares equal to one
            # round-tripped through JSON (json has no tuple type).
            "memo_bodies": sorted([str(n), str(j)] for n, j in bodies),
            "imports": _canon_imports(imports),
            # Coarse intermediate-state check on the frozen arena (node and
            # var counts): catches freeze drift that happens to emit the
            # same bytes. A fresh build() so the stats freeze can't perturb
            # the compiled tree.
            "stats": sess.snapshot_stats(build()),
        }
        if name == "corpus:09_state_var":
            page_kwargs_case = (ident, route, build)

    # One page exercising every optional compile kwarg (title, meta_tags,
    # custom_code, hooks_body) — those template splices are otherwise
    # never covered.
    if page_kwargs_case is not None:
        ident, route, build = page_kwargs_case
        page_js, bodies, imports, *_ = sess.compile_page_from_component_arena(
            build(),
            f"{ident}Kwargs",
            f"{route}_kwargs",
            title="Parity Title",
            meta_tags=[("description", "parity oracle"), ("og:type", "website")],
            custom_code=["// parity custom code"],
            hooks_body="  const parityHook = 1;",
        )
        out["page:kwargs"] = {
            "page_js": page_js,
            "memo_bodies": sorted([str(n), str(j)] for n, j in bodies),
            "imports": _canon_imports(imports),
        }

    out.update(_capture_root_artifacts(sess))
    return out


def _diff(golden: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return human-readable drift lines; empty list means byte-identical."""
    drift: list[str] = []
    for name in sorted(set(golden) | set(current)):
        if name not in golden:
            drift.append(f"{name}: NEW case (not in golden)")
            continue
        if name not in current:
            drift.append(f"{name}: MISSING case (in golden, not produced now)")
            continue
        g, c = golden[name], current[name]
        for field in sorted(set(g) | set(c)):
            if g.get(field) != c.get(field):
                drift.append(f"{name}: {field} DIFFERS")
                if isinstance(g.get(field), str) and isinstance(c.get(field), str):
                    drift.extend(_line_diff(g[field], c[field]))
    return drift


def _line_diff(a: str, b: str, limit: int = 8) -> list[str]:
    import difflib

    lines = list(
        difflib.unified_diff(
            a.splitlines(), b.splitlines(), "golden", "current", lineterm=""
        )
    )
    return [f"    {line}" for line in lines[:limit]]


def main() -> int:
    """Run capture or check against the golden snapshot."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    golden_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_GOLDEN

    if mode == "capture":
        data = _capture_all()
        golden_path.write_text(json.dumps(data, indent=1, sort_keys=True))
        print(f"captured {len(data)} cases -> {golden_path}")
        return 0

    if mode == "check":
        if not golden_path.exists():
            print(f"no golden at {golden_path}; run `capture` first")
            return 2
        golden = json.loads(golden_path.read_text())
        current = _capture_all()
        drift = _diff(golden, current)
        if not drift:
            print(f"OK — {len(current)} cases byte-identical to golden")
            return 0
        print(f"DRIFT in {sum(1 for d in drift if 'DIFFERS' in d or 'case' in d)} field(s):")
        for line in drift:
            print(line)
        return 1

    print(f"unknown mode {mode!r}; use capture|check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
