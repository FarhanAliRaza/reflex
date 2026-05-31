"""Plan §6: per-iter compile budget. After the arena cutover + PR7 var
dedup + PR8 microopts, a medium page compiles in <= 12 ms on this CI
hardware.

The fixture is a synthetic vstack with state-reading text + buttons
roughly matching the snakker page shape (4 pages × ~50 nodes). The
budget is intentionally generous: tighter wall-clock numbers go in
``scripts/benchmark_compile.py``; this test guards the budget that the
plan called out as a regression gate.
"""

from __future__ import annotations

import time

import pytest

import reflex as rx
from reflex.compiler.session import CompilerSession


class _BenchState(rx.State):
    count: int = 0
    items: list[str] = ["a", "b", "c", "d", "e", "f", "g", "h"]

    def increment(self) -> None:
        self.count += 1


def _medium_page():
    return rx.vstack(
        rx.heading("Bench page"),
        *(
            rx.hstack(
                rx.text(f"Row {i} count={_BenchState.count}"),
                rx.button(f"Btn {i}", on_click=_BenchState.increment),
            )
            for i in range(15)
        ),
        rx.foreach(_BenchState.items, lambda item: rx.text(item)),
    )


@pytest.mark.benchmark
def test_pipeline_budget_medium_page_under_12ms() -> None:
    sess = CompilerSession()
    # Warmup
    sess.compile_page_from_component_arena(_medium_page(), "Index", "/")

    # Measure 50 iterations, take the median to dodge timer noise.
    samples = []
    for _ in range(50):
        comp = _medium_page()
        t0 = time.perf_counter_ns()
        sess.compile_page_from_component_arena(comp, "Index", "/")
        samples.append(time.perf_counter_ns() - t0)
    samples.sort()
    median_us = samples[len(samples) // 2] / 1000.0
    assert median_us <= 12_000, (
        f"median arena compile {median_us:.0f} µs exceeds the 12 ms "
        "budget — PR7/PR8 microopts regressed?"
    )


@pytest.mark.benchmark
def test_pipeline_no_legacy_calls() -> None:
    """The arena entry point must not internally route through the
    deleted msgpack tree-IR path. If it does, ``compile_page_from_bytes``
    would still be reachable on the underlying native session.
    """
    sess = CompilerSession()
    assert not hasattr(sess._inner, "compile_page_from_bytes")
