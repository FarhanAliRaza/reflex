"""Measure what the dependency-keyed page cache buys.

Builds a file-backed project (real page modules on disk so the import-graph
keys work), then times `rust_pipeline.compile_pages` in the scenarios that
matter:

* no cache          — today's behavior
* cold + store      — first build, paying cache-write overhead
* warm, all hits    — restart / no-change rebuild (fresh cache instance)
* warm, 1 page edit — the hot-reload case: 1 miss, N-1 hits

Run: ``uv run python scripts/measure_cache_compile.py [routes] [runs]``.
"""

from __future__ import annotations

import importlib
import inspect as _inspect
import os
import sys
import tempfile
import time
import typing as _typing
from pathlib import Path

# Python 3.14 / pydantic 2.13 compat shim (see tests/units/conftest.py).
_orig_eval_type = _typing._eval_type
_params = _inspect.signature(_orig_eval_type).parameters
if "prefer_fwd_module" not in _params:

    def _eval_type_compat(*args, **kwargs):
        return _orig_eval_type(
            *args, **{k: v for k, v in kwargs.items() if k in _params}
        )

    _typing._eval_type = _eval_type_compat  # type: ignore[assignment]

REPO = Path(__file__).resolve().parent.parent

import reflex as rx
from reflex.compiler import rust_pipeline
from reflex.compiler.cache import CompileCache
from reflex.compiler.session import CompilerSession

PAGE_SRC = """\
import reflex as rx

from tests.benchmarks.fixtures import _complicated_page

MARKER = "v1"

def page():
    return _complicated_page()
"""


def main() -> int:
    routes = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    root = Path(tempfile.mkdtemp(prefix="rxcache_"))
    os.chdir(root)
    Path(".web/app/routes").mkdir(parents=True, exist_ok=True)
    Path(".web/utils/components").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(REPO))  # so page modules can import the fixture

    for i in range(routes):
        (root / f"rxpage_{i}.py").write_text(PAGE_SRC)

    app = rx.App()
    for i in range(routes):
        mod = importlib.import_module(f"rxpage_{i}")
        app.add_page(mod.page, route=f"/page-{i}")

    sess = CompilerSession()
    cache_dir = root / ".web" / ".rxcache"

    def compile_with(cache):
        t = time.perf_counter_ns()
        rust_pipeline.compile_pages(app, session=sess, cache=cache)
        return (time.perf_counter_ns() - t) / 1e6

    def best(make_cache, warm_runs=runs):
        return min(compile_with(make_cache()) for _ in range(warm_runs))

    # Warm framework caches with an uncached compile first.
    no_cache_first = compile_with(None)
    no_cache_ms = best(lambda: None)
    n = len(app._unevaluated_pages)
    print(f"pages={n}  (first uncached compile: {no_cache_first:.1f} ms)\n")
    print(f"no cache                 {no_cache_ms:8.2f} ms   1.00x")

    cold_ms = compile_with(CompileCache(root, cache_dir, []))
    print(f"cold + store (once)      {cold_ms:8.2f} ms   {no_cache_ms / cold_ms:.2f}x")

    warm_ms = best(lambda: CompileCache(root, cache_dir, []))
    print(
        f"warm, all hits           {warm_ms:8.2f} ms   {no_cache_ms / warm_ms:.2f}x"
        f"   ({warm_ms / n:.2f} ms/page incl. statics)"
    )

    # Hot-reload: edit one page module, everything else hits.
    def edit_one():
        src = (root / "rxpage_0.py").read_text()
        bump = "x" if 'MARKER = "v1"' in src else ""
        (root / "rxpage_0.py").write_text(
            src.replace('MARKER = "v1"', 'MARKER = "v1x"')
            if bump
            else src.replace('MARKER = "v1x"', 'MARKER = "v1"')
        )
        return CompileCache(root, cache_dir, [])

    edit_ms = min(compile_with(edit_one()) for _ in range(runs))
    print(f"warm, 1 of {n} edited     {edit_ms:8.2f} ms   {no_cache_ms / edit_ms:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
