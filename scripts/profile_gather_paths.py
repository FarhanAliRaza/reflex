"""Profiler + direction-finder for the freeze vs gather compile paths.

Run: ``python scripts/profile_gather_paths.py``

Measures, on a realistic ~80-node page, the median compile time of:

* the **freeze** path (Rust walks the Component tree over PyO3, then
  memoize + emit), and
* the **gather** path (Python ``gather_arena`` builds the wire bundle, Rust
  rebuilds the Snapshot + memoize + emit), split into its Python-gather and
  Rust-rebuild+emit halves, and
* the gather path with the page-emit cache warmed (hot-reload hit).

The **goal** of the gather rewrite is that the gather path beats freeze by
moving the heavy value-rendering off the Python side into Rust. This script
prints a PASS/FAIL verdict against that goal plus a cProfile breakdown of
``gather_arena`` so you can see which work still lives in Python.

This is the executable spec the raw-bundle / render-in-Rust implementation
is driven against: today it FAILS (gather renders in Python, so it is ~as
slow as / slightly slower than freeze); it should PASS once rendering moves
to Rust.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time

import reflex as rx
from reflex.compiler.arena_record import gather_arena
from reflex.compiler.session import CompilerSession


class _ProfState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]

    def inc(self) -> None:
        self.counter += 1


def medium_page():
    """A ~80-node page: heading, 15 reactive rows with events, a foreach."""
    return rx.vstack(
        rx.heading("Bench"),
        *(
            rx.hstack(
                rx.text(f"Row {i} count={_ProfState.counter}"),
                rx.button(f"Btn {i}", on_click=_ProfState.inc),
            )
            for i in range(15)
        ),
        rx.foreach(_ProfState.items, lambda item: rx.text(item)),
    )


def _median_us(samples: list[int]) -> float:
    samples.sort()
    return samples[len(samples) // 2] / 1000.0


def main() -> int:
    sess = CompilerSession()
    n = 120
    node_count = len(sess.dump_snapshot(medium_page())["nodes"])
    print(f"page node count: {node_count}\n")

    for _ in range(10):  # warm per-class caches + intern table
        c = medium_page()
        sess.compile_page_from_component_arena(c, "Index", "/")
        gather_arena(c)

    freeze = []
    for _ in range(n):
        c = medium_page()
        t = time.perf_counter_ns()
        sess.compile_page_from_component_arena(c, "Index", "/")
        freeze.append(time.perf_counter_ns() - t)

    gather_py, arena_rust, gather_total = [], [], []
    for _ in range(n):
        c = medium_page()
        t0 = time.perf_counter_ns()
        bundle = gather_arena(c)
        t1 = time.perf_counter_ns()
        sess.compile_page_from_arena(bundle, "Index", "/", compute_close=True)
        t2 = time.perf_counter_ns()
        gather_py.append(t1 - t0)
        arena_rust.append(t2 - t1)
        gather_total.append(t2 - t0)

    sess.set_emit_cache_enabled(True)
    sess.compile_page_from_arena(gather_arena(medium_page()), "Index", "/", compute_close=True)
    cache_hit = []
    for _ in range(n):
        c = medium_page()
        t = time.perf_counter_ns()
        sess.compile_page_from_arena(gather_arena(c), "Index", "/", compute_close=True)
        cache_hit.append(time.perf_counter_ns() - t)
    sess.set_emit_cache_enabled(False)

    f, g, ch = _median_us(freeze), _median_us(gather_total), _median_us(cache_hit)
    print(f"FREEZE path                         median = {f:8.1f} us")
    print(f"GATHER path total                   median = {g:8.1f} us")
    print(f"  gather() Python only              median = {_median_us(gather_py):8.1f} us")
    print(f"  Rust rebuild+memoize+emit         median = {_median_us(arena_rust):8.1f} us")
    print(f"GATHER + emit-cache HIT             median = {ch:8.1f} us")
    print(f"\ngather vs freeze:    {f / g:.2f}x")
    print(f"cache-hit vs freeze: {f / ch:.2f}x")

    # Diagnose where gather() spends time.
    pr = cProfile.Profile()
    pages = [medium_page() for _ in range(60)]
    pr.enable()
    for c in pages:
        gather_arena(c)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(12)
    print("\n--- gather_arena cProfile (top 12 cumulative) ---")
    print("\n".join(s.getvalue().splitlines()[4:20]))

    # Verdict: the gather path should be faster than freeze (target: a
    # comfortable margin so it survives container noise).
    goal_met = g < f
    print(f"\n{'PASS' if goal_met else 'FAIL'}: gather path "
          f"{'beats' if goal_met else 'does NOT beat'} freeze "
          f"({f / g:.2f}x). Target: gather < freeze "
          "(rendering must move from Python to Rust).")
    return 0 if goal_met else 1


if __name__ == "__main__":
    sys.exit(main())
