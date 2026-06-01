"""De-risking spike for a Rust-backed (PyO3) Var system.

Pure-Python Var construction is the framework's real bottleneck — a single
``State.x + 1`` costs ~31us (expression-tree build + type inference +
var_data merge + render), while a PyO3 crossing is ~100ns. This spike pins
the result that justifies rewriting the ``Var`` base in Rust: a minimal
Rust-backed Var (``_native.SpikeVar``) renders byte-identical ``_js_expr``
and builds each op ~80-90x faster, and Python composes it transparently
(operators / reflected ops / nesting).

If this stays green, the full rewrite — operators, typed ``__getattr__``,
indexing, ``.to()``, casting, var_data propagation, format-strings, all in
PyO3 with identical Python semantics — is worth the lift. If it ever fails,
the premise (Rust Vars are dramatically faster + byte-identical) no longer
holds.
"""

from __future__ import annotations

import time

import pytest
from reflex_compiler_rust import _native

import reflex as rx


class _SpikeState(rx.State):
    counter: int = 0


def _py_leaf():
    return _SpikeState.counter


def _rust_leaf():
    # Seed the Rust leaf with the Python leaf's exact rendered ref (state-name
    # mangling is Python's job and not what this spike tests) — the spike
    # validates the Rust-side *op composition* + render speed.
    return _native.SpikeVar.literal(_SpikeState.counter._js_expr)


@pytest.mark.parametrize(
    "build",
    [
        lambda v: v,  # leaf
        lambda v: v + 1,
        lambda v: v > 0,
        lambda v: v * 2,
        lambda v: 1 + v,  # reflected add
        lambda v: (v + 1) > 0,  # nested
        lambda v: v < 5,
        lambda v: v >= 10,
    ],
)
def test_rust_var_byte_identical(build) -> None:
    """The Rust-backed Var renders the same ``_js_expr`` as the Python Var."""
    assert build(_rust_leaf())._js_expr == build(_py_leaf())._js_expr


def _median_ns(fn, reps: int = 8000) -> int:
    for _ in range(500):
        fn()
    samples = []
    for _ in range(reps):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    samples.sort()
    return samples[len(samples) // 2]


@pytest.mark.benchmark
def test_rust_var_is_much_faster() -> None:
    """A Rust-backed Var op must be dramatically cheaper than the Python op.

    Relative comparison (same machine/run) so it is robust to absolute
    speed; the measured headroom is ~88x, so a conservative 5x floor stays
    green under container noise while still catching a regression of the
    premise.
    """
    py = _py_leaf()
    ru = _rust_leaf()
    py_ns = _median_ns(lambda: py + 1)
    ru_ns = _median_ns(lambda: ru + 1)
    assert ru_ns * 5 < py_ns, (
        f"Rust Var op not dramatically faster: rust={ru_ns}ns "
        f"python={py_ns}ns ({py_ns / ru_ns:.1f}x)"
    )
