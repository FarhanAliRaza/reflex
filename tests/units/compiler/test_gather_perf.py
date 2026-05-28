"""Performance goal for the gather path (PR D/F direction-finder).

The whole point of moving the per-node read off the PyO3 boundary into a
Python ``gather_arena`` walk is that the gather path should be **faster**
than the Rust freeze walk. This test encodes that goal as a *relative*
median comparison (relative, so it cancels out absolute machine speed and
container load): the gather path must come in at or below the freeze path.

It FAILS today on purpose — the current gather implementation renders
values to JS in Python (event chains, var exprs, ``_get_imports``), so it
pays the same heavy cost as freeze plus dict-build + Rust-rebuild overhead.
It should PASS once that rendering moves to Rust (the raw-bundle /
render-in-Rust refactor), at which point Python only does cheap native
attribute reads.

Run alone: ``pytest tests/units/compiler/test_gather_perf.py``.
"""

from __future__ import annotations

import time

import pytest

import reflex as rx
from reflex.compiler.arena_record import gather_arena
from reflex.compiler.session import CompilerSession


class _PerfState(rx.State):
    counter: int = 0
    items: list[str] = ["a", "b", "c"]

    def inc(self) -> None:
        self.counter += 1


def _medium_page():
    return rx.vstack(
        rx.heading("Bench"),
        *(
            rx.hstack(
                rx.text(f"Row {i} count={_PerfState.counter}"),
                rx.button(f"Btn {i}", on_click=_PerfState.inc),
            )
            for i in range(15)
        ),
        rx.foreach(_PerfState.items, lambda item: rx.text(item)),
    )


def _median_ns(samples: list[int]) -> int:
    samples.sort()
    return samples[len(samples) // 2]


def _bench(n: int = 80) -> tuple[int, int]:
    sess = CompilerSession()
    for _ in range(10):  # warm per-class caches
        c = _medium_page()
        sess.compile_page_from_component_arena(c, "Index", "/")
        gather_arena(c)

    freeze, gather = [], []
    # Interleave so transient load hits both paths equally.
    for _ in range(n):
        c = _medium_page()
        t = time.perf_counter_ns()
        sess.compile_page_from_component_arena(c, "Index", "/")
        freeze.append(time.perf_counter_ns() - t)

        c = _medium_page()
        t = time.perf_counter_ns()
        bundle = gather_arena(c)
        sess.compile_page_from_arena(bundle, "Index", "/", compute_close=True)
        gather.append(time.perf_counter_ns() - t)
    return _median_ns(freeze), _median_ns(gather)


@pytest.mark.benchmark
@pytest.mark.xfail(
    reason="gather currently renders values in Python, so it is ~as slow as "
    "freeze; flips to PASS once rendering moves to Rust (raw-bundle refactor)",
    strict=False,
)
def test_gather_path_beats_freeze() -> None:
    """The gather path's median compile must be <= the freeze path's.

    Relative comparison on the same machine in the same run, so it is robust
    to absolute speed / container load. Fails while gather renders in
    Python; passes once rendering is done in Rust from a raw bundle.
    """
    freeze_ns, gather_ns = _bench()
    ratio = gather_ns / freeze_ns
    assert gather_ns <= freeze_ns, (
        f"gather path is slower than freeze: gather={gather_ns / 1000:.0f}us "
        f"freeze={freeze_ns / 1000:.0f}us ({ratio:.2f}x). The gather walk "
        "must move value-rendering to Rust so Python only reads raw attrs."
    )
