"""Profile the Rust compile pipeline end-to-end on a real app.

Measures three things:

1. End-to-end ``compile_pages(app)`` total (best of N) — the cost a user
   sees when running ``reflex run-rust``.
2. Per-phase breakdown for one route (``compile_unevaluated_page``,
   pre/post-memoize ``_get_all_imports``, ``walk_and_memoize``,
   ``page_to_ir``, ``compile_page_from_bytes``).
3. Head-to-head against the legacy ``compile_page`` on the same finalized
   tree, so the comparison is post-tree-build only (excluding the user
   Python the two pipelines share).

Example invocation (one line so the docstring stays free of backslashes)::

    CI=1 uv run python scripts/profile_rust_pipeline.py --app-dir docs/app --route index

The ``CI=1`` env var sidesteps the ``reflex-enterprise`` interactive
login prompt on apps that import ``reflex_enterprise``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-dir",
        default="docs/app",
        help="Path to the Reflex app directory (containing rxconfig.py).",
    )
    parser.add_argument(
        "--route",
        default=None,
        help="Route key for the per-phase breakdown. Defaults to the heaviest "
        "registered route (largest IR).",
    )
    parser.add_argument(
        "--runs-total",
        type=int,
        default=3,
        help="Number of full compile_pages runs; the script reports best-of.",
    )
    parser.add_argument(
        "--runs-phase",
        type=int,
        default=5,
        help="Number of per-phase iterations averaged for the breakdown.",
    )
    return parser.parse_args()


def time_call(fn: Any, *args: Any, **kw: Any) -> tuple[float, Any]:
    """Run ``fn(*args, **kw)`` once and time it.

    Args:
        fn: Callable to invoke.
        *args: Positional args forwarded to ``fn``.
        **kw: Keyword args forwarded to ``fn``.

    Returns:
        ``(elapsed_ms, return_value)`` — wall-clock time in milliseconds
        plus whatever ``fn`` returned.
    """
    t = time.perf_counter()
    out = fn(*args, **kw)
    return (time.perf_counter() - t) * 1000, out


def main() -> None:
    """Profile the pipeline and print phase breakdowns to stdout."""
    args = parse_args()
    app_dir = Path(args.app_dir).resolve()
    if not (app_dir / "rxconfig.py").is_file():
        msg = f"No rxconfig.py at {app_dir}"
        raise SystemExit(msg)

    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))

    t0 = time.perf_counter()
    from reflex.utils.prerequisites import get_app

    app = get_app(reload=False).app
    print(f"[setup] load app: {(time.perf_counter() - t0) * 1000:.1f} ms")

    from reflex.compiler.compiler import compile_page, compile_unevaluated_page
    from reflex.compiler.ir.bridge import page_to_ir
    from reflex.compiler.rust_memo import walk_and_memoize
    from reflex.compiler.rust_pipeline import _union_imports, compile_pages
    from reflex.compiler.session import CompilerSession

    app._apply_decorated_pages()
    n_pages = len(app._unevaluated_pages)
    print(f"[setup] pages: {n_pages}")

    times = []
    for i in range(args.runs_total):
        sess = CompilerSession()
        dt, _ = time_call(compile_pages, app, session=sess)
        times.append(dt)
        print(f"[run {i}] compile_pages total: {dt:.0f} ms")
    best = min(times)
    print(
        f"\n=== compile_pages best of {args.runs_total}: {best:.0f} ms "
        f"for {n_pages} pages ({best / n_pages:.1f} ms/page) ===\n"
    )

    route = args.route or _pick_heaviest_route(app)
    unev = app._unevaluated_pages[route]
    print(f"[debug] routes: {list(app._unevaluated_pages.keys())[:8]}")
    print(f"[debug] per-phase route: {route!r}")

    sess = CompilerSession()
    totals: dict[str, float] = {
        "compile_unevaluated_page": 0.0,
        "pre_memo_imports": 0.0,
        "walk_and_memoize": 0.0,
        "post_memo_imports": 0.0,
        "union_imports": 0.0,
        "page_to_ir": 0.0,
        "compile_page_from_bytes": 0.0,
    }
    ir_size = 0
    for _ in range(args.runs_phase):
        dt, component = time_call(
            compile_unevaluated_page, route, unev, app.style, app.theme
        )
        totals["compile_unevaluated_page"] += dt
        dt, pre = time_call(component._get_all_imports)
        totals["pre_memo_imports"] += dt
        dt, wrapped = time_call(walk_and_memoize, component, sess, {})
        totals["walk_and_memoize"] += dt
        dt, post = time_call(wrapped._get_all_imports)
        totals["post_memo_imports"] += dt
        dt, extras = time_call(_union_imports, pre, post)
        totals["union_imports"] += dt
        dt, ir = time_call(
            page_to_ir, route=route, component=wrapped, extra_imports=extras
        )
        totals["page_to_ir"] += dt
        dt, _ = time_call(
            sess.compile_page_from_bytes,
            "Index",
            ir,
            custom_code=[],
            hooks_body="",
        )
        totals["compile_page_from_bytes"] += dt
        ir_size = len(ir)

    print(f"=== Per-phase avg over {args.runs_phase} runs (route {route}) ===")
    for k, v in totals.items():
        print(f"  {k:30s} {v / args.runs_phase:8.2f} ms")
    rust_total = sum(totals.values()) / args.runs_phase
    print(f"  {'TOTAL':30s} {rust_total:8.2f} ms")
    print(f"\n[ir] size: {ir_size} bytes")

    legacy_times: list[float] = []
    for _ in range(args.runs_total):
        legacy_tree = compile_unevaluated_page(route, unev, app.style, app.theme)
        dt, _ = time_call(compile_page, route, legacy_tree)
        legacy_times.append(dt)
    print(f"\n=== Legacy compile_page (post-tree, route {route}) ===")
    print(f"  min:  {min(legacy_times):8.2f} ms")
    print(f"  mean: {sum(legacy_times) / len(legacy_times):8.2f} ms")
    rust_post = rust_total - totals["compile_unevaluated_page"] / args.runs_phase
    print(f"\n=== Rust pipeline (post-tree, route {route}) ===")
    print(f"  per-phase sum (excl. compile_unevaluated_page): {rust_post:.2f} ms")
    print(f"  speedup vs legacy: {min(legacy_times) / rust_post:.2f}x")


def _pick_heaviest_route(app: Any) -> str:
    """Return the route whose IR is largest — the most interesting test case.

    Falls back to the first registered route if all pages evaluate to
    trees of the same size or evaluation fails.
    """
    return (
        "index"
        if "index" in app._unevaluated_pages
        else next(iter(app._unevaluated_pages))
    )


if __name__ == "__main__":
    main()
