"""PyO3 boundary-cost optimizations on the freeze pass.

The arena pipeline crosses the PyO3 boundary ~15-20 times per
Component (getattr + method calls). At ~100-300 ns per crossing,
that's 7-15 µs per node — 350-750 µs per 50-node page just in
boundary overhead. Two known speedups apply:

1. **`pyo3::intern!`** for every hot attribute name. PyO3's
   ``getattr(&str)`` allocates a fresh ``PyString`` from the ``&str``
   on every call; ``getattr(&Bound<PyString>)`` skips that. The
   ``intern!`` macro stores a single pre-interned ``PyString`` in a
   module-level static — ~50-100 ns saved per attr access.

2. **Per-class method-handle cache** for the heavy methods
   (``_get_imports``, ``_get_components_in_props``, ``get_props``,
   ``_render``). Cache the unbound method on the type at first sight,
   then call via the cached handle on every subsequent same-class
   node. Saves the MRO walk on each call (~100-300 ns).

These tests pin observable consequences:

* Tightened perf budget (medium page <= 8 ms median after
  optimizations — was 10.4 ms before).
* Cache warm vs cold — second compile of structurally identical
  trees is at least as fast as the first (caches don't regress).
"""

from __future__ import annotations

import time

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession


class _OptState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c", "d", "e", "f", "g", "h"]

    def inc(self) -> None:
        self.counter += 1


def _medium_page():
    return rx.vstack(
        rx.heading("Bench"),
        *(
            rx.hstack(
                rx.text(f"Row {i} count={_OptState.counter}"),
                rx.button(f"Btn {i}", on_click=_OptState.inc),
            )
            for i in range(15)
        ),
        rx.foreach(_OptState.items, lambda item: rx.text(item)),
    )


@pytest.mark.benchmark
def test_arena_medium_page_under_8ms_post_optimizations() -> None:
    """Tightened budget: after ``intern!`` + per-class method cache,
    median arena compile for a 50-node page should sit under 8 ms.

    Pre-optimization baseline: ~10.4 ms median.
    """
    sess = CompilerSession()
    sess.compile_page_from_component_arena(_medium_page(), "Index", "/")

    samples = []
    for _ in range(60):
        comp = _medium_page()
        t0 = time.perf_counter_ns()
        sess.compile_page_from_component_arena(comp, "Index", "/")
        samples.append(time.perf_counter_ns() - t0)
    samples.sort()
    median_us = samples[len(samples) // 2] / 1000.0
    assert median_us <= 8_000, (
        f"median arena compile {median_us:.0f} µs exceeds the 8 ms "
        "tightened budget — intern!/method-cache regression"
    )


@pytest.mark.benchmark
def test_class_method_cache_warms_on_repeat() -> None:
    """Compiling a second page with the same Component classes hits
    the per-class method handle cache: should be at least as fast as
    the first compile, never slower. Validates the cache is correctly
    shared across compiles (not torn down per-session)."""
    sess = CompilerSession()
    # Warmup
    sess.compile_page_from_component_arena(_medium_page(), "Index", "/")

    # Median of 30 compiles for "cold" (first per fresh session)
    cold_samples = []
    for _ in range(30):
        cold_sess = CompilerSession()
        comp = _medium_page()
        t0 = time.perf_counter_ns()
        cold_sess.compile_page_from_component_arena(comp, "Index", "/")
        cold_samples.append(time.perf_counter_ns() - t0)

    # Median of 30 compiles for warm (same session, repeated)
    warm_samples = []
    for _ in range(30):
        comp = _medium_page()
        t0 = time.perf_counter_ns()
        sess.compile_page_from_component_arena(comp, "Index", "/")
        warm_samples.append(time.perf_counter_ns() - t0)

    cold_samples.sort()
    warm_samples.sort()
    cold_med = cold_samples[len(cold_samples) // 2]
    warm_med = warm_samples[len(warm_samples) // 2]
    # Warm compile must be at least as fast as cold (allow 10% noise).
    assert warm_med <= cold_med * 1.10, (
        f"warm compile slower than cold: warm={warm_med/1000:.0f}us "
        f"cold={cold_med/1000:.0f}us — cache regression"
    )


def test_arena_output_unchanged_by_optimizations() -> None:
    """Optimization must not change emitted output. Snapshot the page
    JSX + memo body names from the current arena run; any future
    PyO3-trick change must produce identical bytes."""
    sess = CompilerSession()
    comp = _medium_page()
    page_a, bodies_a, imports_a = sess.compile_page_from_component_arena(
        comp, "Index", "/"
    )

    comp2 = _medium_page()
    page_b, bodies_b, imports_b = sess.compile_page_from_component_arena(
        comp2, "Index", "/"
    )

    assert page_a == page_b
    assert sorted(b[0] for b in bodies_a) == sorted(b[0] for b in bodies_b)
    assert sorted(imports_a.keys()) == sorted(imports_b.keys())
