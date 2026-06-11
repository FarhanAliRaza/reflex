"""Measure page-level parallelism for the Rust compile pipeline.

Pages are independent (evaluate -> arena freeze -> emit -> write), so the
per-page loop in ``rust_pipeline.compile_pages`` is embarrassingly parallel
in principle. This script measures what that buys in practice:

* sequential baseline (the loop as written today),
* threads (expected ~1x on a GIL build: construction + freeze hold the GIL),
* fork-per-run worker processes (cold-start cost included every run),
* a persistent fork Pool (fork + COW-fault storm paid once, then steady-state
  throughput — the shape a parallel ``compile_pages`` would actually use).

Run: ``uv run python scripts/measure_parallel_compile.py [routes] [runs]``.
"""

from __future__ import annotations

import inspect as _inspect
import multiprocessing as mp
import os
import sys
import tempfile
import time
import typing as _typing
from concurrent.futures import ThreadPoolExecutor
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

import reflex as rx
from reflex.compiler import rust_pipeline, utils as compiler_utils
from reflex.compiler.session import CompilerSession

PAGES: list[tuple[str, object]] = []
APP = None
# The Rust CompilerSession is unsendable (thread-affine), so each thread —
# and each forked worker — gets its own via thread-local storage.
_TLS = __import__("threading").local()


def _build_app(route_count: int):
    """A synthetic app alternating rich + stateful pages.

    Args:
        route_count: How many routes to register.

    Returns:
        The populated ``rx.App``.
    """
    from tests.benchmarks.fixtures import _complicated_page, _stateful_page

    app = rx.App()
    for i in range(route_count):
        builder = _complicated_page if i % 2 == 0 else _stateful_page

        def make(idx: int, fn: object = builder):
            def _page():
                return fn()

            _page.__name__ = f"page_{idx}"
            return _page

        app.add_page(make(i), route=f"/page-{i}")
    return app


def compile_chunk(indices: list[int]) -> None:
    """The per-page work from rust_pipeline.compile_pages, for a route subset.

    Uses a lazily-created thread-local CompilerSession (the Rust session is
    unsendable) so pool workers and threads each pay session setup once, not
    per chunk.

    Args:
        indices: Positions into the module-global ``PAGES`` list.
    """
    from reflex.compiler.compiler import compile_unevaluated_page

    sess = getattr(_TLS, "sess", None)
    if sess is None:
        sess = _TLS.sess = CompilerSession()
    components_dir = Path(compiler_utils.get_memo_components_dir())
    for i in indices:
        route, unev = PAGES[i]
        component = compile_unevaluated_page(route, unev, APP.style, APP.theme)
        ident = rust_pipeline._route_to_ident(route)
        out_path = Path(compiler_utils.get_page_path(route))
        rust_js, memo_bodies, _imports, *_ = sess.compile_page_from_component_arena(
            component, ident, route, title=None, meta_tags=None
        )
        sess.write_if_changed(str(out_path), rust_js)
        for name, jsx in memo_bodies:
            sess.write_if_changed(str(components_dir / f"{name}.jsx"), jsx)


def _fresh_worker_session(_: object = None) -> None:
    """Pool initializer: drop any session inherited via fork."""
    _TLS.sess = None


def _chunks(n_items: int, n_chunks: int) -> list[list[int]]:
    """Snake-order page indices into balanced chunks.

    Plain round-robin with w=2 would put every heavy page in one chunk
    (page shapes alternate); snake order interleaves both shapes.

    Args:
        n_items: Number of page indices to distribute.
        n_chunks: Number of chunks.

    Returns:
        Non-empty chunks of page indices.
    """
    out: list[list[int]] = [[] for _ in range(n_chunks)]
    for i in range(n_items):
        k = i % (2 * n_chunks)
        w = k if k < n_chunks else 2 * n_chunks - 1 - k
        out[w].append(i)
    return [c for c in out if c]


def _time_best(fn: object, runs: int) -> float:
    """Best-of-N wall-clock time for a thunk, in milliseconds.

    Args:
        fn: Zero-arg callable to time.
        runs: How many repetitions to take the minimum over.

    Returns:
        The fastest run in milliseconds.
    """
    best = float("inf")
    for _ in range(runs):
        t = time.perf_counter_ns()
        fn()
        best = min(best, time.perf_counter_ns() - t)
    return best / 1e6


def main() -> int:
    """Run the parallelism measurement matrix.

    Returns:
        Process exit code.
    """
    global APP, PAGES
    routes = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    APP = _build_app(routes)

    tmp = tempfile.mkdtemp(prefix="rxparallel_")
    os.chdir(tmp)
    Path(".web/app/routes").mkdir(parents=True, exist_ok=True)
    Path(".web/utils/components").mkdir(parents=True, exist_ok=True)

    # Warm everything in the parent: per-class caches, intern table, state
    # registration, theme styles. Forked children inherit all of it via COW.
    rust_pipeline.compile_pages(APP, session=CompilerSession())
    PAGES = list(APP._unevaluated_pages.items())
    n = len(PAGES)
    all_indices = list(range(n))

    seq_ms = _time_best(lambda: compile_chunk(all_indices), runs)
    print(f"pages={n}  cores={os.cpu_count()}  gil={sys._is_gil_enabled()}")
    print(f"\nsequential                     {seq_ms:8.2f} ms   1.00x")

    for w in (2, 4, 8):
        chunks = _chunks(n, w)

        def run_threads(chunks: list[list[int]] = chunks):
            with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
                list(ex.map(compile_chunk, chunks))

        ms = _time_best(run_threads, runs)
        print(f"threads        w={w:<2}            {ms:8.2f} ms   {seq_ms / ms:.2f}x")

    ctx = mp.get_context("fork")

    for w in (2, 4, 8, 12):
        chunks = _chunks(n, w)

        def run_fork(chunks: list[list[int]] = chunks):
            procs = [ctx.Process(target=compile_chunk, args=(c,)) for c in chunks]
            for p in procs:
                p.start()
            for p in procs:
                p.join()
            if any(p.exitcode != 0 for p in procs):
                msg = "worker failed"
                raise RuntimeError(msg)

        ms = _time_best(run_fork, runs)
        print(f"fork-per-run   w={w:<2}            {ms:8.2f} ms   {seq_ms / ms:.2f}x")

    # Persistent pool: fork + first-touch COW faults paid once at pool
    # creation/warmup, then measure steady-state throughput with dynamic
    # load balancing (4 chunks per worker).
    for w in (2, 4, 8, 12):
        with ctx.Pool(w, initializer=_fresh_worker_session) as pool:
            work = _chunks(n, min(n, w * 4))
            pool.map(compile_chunk, work)  # warmup: sessions + COW faults
            ms = _time_best(
                lambda pool=pool, work=work: pool.map(compile_chunk, work), runs
            )
        print(f"pool (warm)    w={w:<2}            {ms:8.2f} ms   {seq_ms / ms:.2f}x")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
