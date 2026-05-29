"""Profile the FULL page compile through the production Rust pipeline.

Runs ``reflex.compiler.rust_pipeline.compile_pages`` end-to-end on a synthetic
multi-route app — the real production path: evaluate page (Python) -> Rust
freeze/gather -> Rust memoize+emit -> write JSX. Times it per route and
cProfiles the whole thing so the slow parts of the *full* Rust compile are
visible (framework construction vs Rust freeze vs emit vs file writes).

Run: ``uv run python scripts/profile_full_rust_compile.py [routes] [runs]``.
"""

from __future__ import annotations

import cProfile
import inspect as _inspect
import io
import os
import pstats
import sys
import tempfile
import time
import typing as _typing

# Python 3.14 / pydantic 2.13 compat shim (see tests/units/conftest.py).
_orig_eval_type = _typing._eval_type
_params = _inspect.signature(_orig_eval_type).parameters
if "prefer_fwd_module" not in _params:

    def _eval_type_compat(*args, **kwargs):
        return _orig_eval_type(
            *args, **{k: v for k, v in kwargs.items() if k in _params}
        )

    _typing._eval_type = _eval_type_compat  # type: ignore[assignment]

import reflex as rx
from reflex.compiler import rust_pipeline
from reflex.compiler.session import CompilerSession


def _build_app(route_count: int):
    """A synthetic app of ``route_count`` rich + stateful pages."""
    from tests.benchmarks.fixtures import _complicated_page, _stateful_page

    app = rx.App()
    for i in range(route_count):
        builder = _complicated_page if i % 2 == 0 else _stateful_page

        def make(idx: int, fn=builder):
            def _page():
                return fn()

            _page.__name__ = f"page_{idx}"
            return _page

        app.add_page(make(i), route=f"/page-{i}")
    return app


def main() -> int:
    """Run + profile the full Rust compile pipeline."""
    routes = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    app = _build_app(routes)
    n_routes = len(app._unevaluated_pages)

    # Compile from a scratch dir so JSX writes land somewhere disposable.
    tmp = tempfile.mkdtemp(prefix="rxcompile_")
    os.chdir(tmp)
    os.makedirs(".web/app/routes", exist_ok=True)
    os.makedirs(".web/utils/components", exist_ok=True)

    sess = CompilerSession()

    # Warm: per-class caches, intern table, emit cache off (cold each run).
    rust_pipeline.compile_pages(app, session=sess)

    samples = []
    for _ in range(runs):
        t = time.perf_counter_ns()
        rust_pipeline.compile_pages(app, session=sess)
        samples.append(time.perf_counter_ns() - t)
    samples.sort()
    median_ms = samples[len(samples) // 2] / 1_000_000

    print(f"Full Rust compile: {n_routes} routes, {runs} runs")
    print(
        f"  median total      {median_ms:8.2f} ms  ({median_ms / n_routes:.2f} ms/route)\n"
    )

    # cProfile one full compile to see where the time goes.
    pr = cProfile.Profile()
    pr.enable()
    rust_pipeline.compile_pages(app, session=sess)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(20)
    print("--- cProfile (top cumulative) ---")
    print("\n".join(s.getvalue().splitlines()[4:26]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
