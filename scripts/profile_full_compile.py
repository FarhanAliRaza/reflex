"""Full-compile profile: where the Rust Var lands the page-compile pipeline.

The earlier per-op benchmark (``profile_rust_var.py``) shows ~3.4x on isolated
Var operations. This answers the question that actually matters: *how fast is a
whole page compile once the Var construction runs in Rust?*

It measures, on a realistic ~80-node page, the real pipeline breakdown and then
substitutes the **measured** Rust-Var construction cost for the Python var-build
portion:

* ``component-object build`` — the Python floor (building Component objects),
  which a Rust Var cannot touch; isolated via a Var-free ``static_page``.
* ``reactive var build`` — constructing the page's reactive expressions (the
  f-string + state-var work); measured both with the Python Var and with the
  Rust Var over equivalent leaves.
* ``compile`` — the Rust gather/emit tail, var-agnostic and unchanged.

The only projection is that the component floor and the compile tail are
var-agnostic (true — neither constructs Vars), so the full-compile time with the
Rust Var is ``floor + rust_var_build + compile``. Everything else is measured on
this machine in this run, so the ratio is robust to absolute speed.

Run: ``uv run python scripts/profile_full_compile.py``.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import reflex as rx
from reflex_compiler_rust import _native
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


def static_page():
    """Same shape, no Vars/events/foreach — isolates the component-object floor."""
    return rx.vstack(
        rx.heading("Bench"),
        *(
            rx.hstack(rx.text(f"Row {i} count=0"), rx.button(f"Btn {i}"))
            for i in range(15)
        ),
        rx.text("a"),
        rx.text("b"),
        rx.text("c"),
    )


# The reactive-var workload a page row builds: an f-string embedding a state
# var. Fifteen rows -> fifteen such expressions, the dominant per-page Var cost.
_ROWS = 15


def build_py_vars() -> None:
    """Build the page's reactive f-string vars with the Python Var."""
    for i in range(_ROWS):
        _ = f"Row {i} count={_ProfState.counter}"  # __format__ + implicit create


def build_rust_vars(rust_counter: object) -> None:
    """Build the same reactive f-string vars with the Rust Var."""
    for i in range(_ROWS):
        _native.rust_create_string(f"Row {i} count={rust_counter}")


def _median_us(fn: Callable[[], object], reps: int = 200) -> float:
    """Median wall-clock microseconds of ``fn`` over ``reps`` runs (warmed)."""
    for _ in range(20):
        fn()
    samples = []
    for _ in range(reps):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    samples.sort()
    return samples[len(samples) // 2] / 1000.0


def main() -> int:
    """Measure the pipeline and project the Rust-Var full-compile time."""
    sess = CompilerSession()
    rust_counter = _native.rust_from_python_var(_ProfState.counter)

    # Warm caches.
    for _ in range(10):
        c = medium_page()
        sess.compile_page_from_arena(gather_arena(c), "Index", "/", compute_close=True)

    def compile_once() -> None:
        c = medium_page()
        sess.compile_page_from_arena(gather_arena(c), "Index", "/", compute_close=True)

    full_construct = _median_us(medium_page)
    floor = _median_us(static_page)
    full_pipeline_py = _median_us(compile_once)
    compile_only = max(full_pipeline_py - full_construct, 0.0)

    # Reactive-var construction, both ways. The Python f-string also builds the
    # surrounding LiteralVar; the Rust path goes through rust_create_string.
    py_var = _median_us(build_py_vars)
    rust_var = _median_us(lambda: build_rust_vars(rust_counter))

    # Substitute the Rust var-build for the Python var portion of construction.
    # The reactive var build is a measured slice of full construction; the
    # remainder (component objects + events + foreach) is the var-agnostic floor.
    projected_construct = floor + rust_var
    projected_full = projected_construct + compile_only

    print(f"page reactive-var rows: {_ROWS}\n")
    print("--- measured pipeline (Python Var) ---")
    print(f"  component-object floor (static)   {floor:8.1f} us  (Rust-Var-immune)")
    print(f"  reactive var build (Python)       {py_var:8.1f} us")
    print(f"  full construction                 {full_construct:8.1f} us")
    print(f"  compile (gather tail)             {compile_only:8.1f} us  (var-agnostic)")
    print(f"  FULL pipeline (Python Var)        {full_pipeline_py:8.1f} us\n")

    print("--- reactive var build, Python vs Rust ---")
    print(f"  Python Var                        {py_var:8.1f} us")
    print(f"  Rust Var                          {rust_var:8.1f} us")
    print(f"  var-build speedup                 {py_var / rust_var:7.1f}x\n")

    print("--- projected full compile (Rust Var) ---")
    print(f"  floor + rust_var + compile        {projected_full:8.1f} us")
    print(
        f"  FULL pipeline speedup             {full_pipeline_py / projected_full:7.2f}x"
    )
    print(
        f"  (reactive var build is {py_var / full_pipeline_py * 100:.0f}% of the "
        "Python pipeline; that slice shrinks, the rest is fixed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
