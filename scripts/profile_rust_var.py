"""Benchmark the Rust ``Var`` against the Python ``Var`` across the full corpus.

The Rust Var cutover is motivated by speed: pure-Python Var construction is the
framework's bottleneck (a single ``State.x + 1`` runs ~30us — expression-tree
build + type inference + var_data merge + render), while a PyO3 crossing is
~100ns. Now that ``RustVar`` reproduces the *entire* golden corpus
byte-for-byte, this measures the actual end-to-end speedup per operation class
(construction, arithmetic, comparison, string/array/object methods, var_data
merge), so the cutover's payoff is quantified, not assumed.

Run: ``uv run python scripts/profile_rust_var.py``. Prints, per operation, the
median Python-Var vs Rust-Var time and the speedup factor. Relative comparison
on the same machine/run, so it is robust to absolute speed / container load.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import reflex as rx
from reflex.vars import Var
from reflex_compiler_rust import _native


class _BenchState(rx.State):
    count: int = 0
    flag: bool = False
    name: str = "n"
    items: list[int] = [1, 2, 3]
    data: dict[str, int] = {"a": 1}


def _rust_leaf(py_leaf: Var) -> object:
    """Seed a Rust leaf from a Python state var (js_expr + type + var_data)."""
    return _native.rust_from_python_var(py_leaf)


def _median_ns(fn: Callable[[], object], reps: int = 4000) -> int:
    """Median wall-clock ns of ``fn`` over ``reps`` runs (after warmup)."""
    for _ in range(400):
        fn()
    samples = []
    for _ in range(reps):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    samples.sort()
    return samples[len(samples) // 2]


def _cases() -> dict[str, tuple[Callable[[], object], Callable[[], object]]]:
    """Map each op to (python_builder, rust_builder) over equivalent leaves."""
    s = _BenchState
    # Rust leaves are seeded once; the timed closure does only the operation,
    # mirroring the Python side which operates on the cached state leaf.
    rc, rf, rn, ri, rd = (
        _rust_leaf(s.count),
        _rust_leaf(s.flag),
        _rust_leaf(s.name),
        _rust_leaf(s.items),
        _rust_leaf(s.data),
    )
    return {
        "arith (x + 1)": (lambda: s.count + 1, lambda: rc + 1),
        "compare (x > 0)": (lambda: s.count > 0, lambda: rc > 0),
        "nested ((x+1)*2>4)": (
            lambda: (s.count + 1) * 2 > 4,
            lambda: (rc + 1) * 2 > 4,
        ),
        "bool (a & b)": (
            lambda: s.flag & (s.count > 0),
            lambda: rf & (rc > 0),
        ),
        "str.lower()": (lambda: s.name.lower(), lambda: rn.lower()),
        "str concat (s+!)": (lambda: s.name + "!", lambda: rn + "!"),
        "str.length()": (lambda: s.name.length(), lambda: rn.length()),
        "arr.length()": (lambda: s.items.length(), lambda: ri.length()),
        "arr[0]": (lambda: s.items[0], lambda: ri[0]),
        "obj['a']": (lambda: s.data["a"], lambda: rd["a"]),
        "var_data merge": (
            lambda: (s.count + 1)._get_all_var_data(),
            lambda: (rc + 1)._get_all_var_data(),
        ),
    }


def main() -> int:
    """Run the benchmark and print per-op Python vs Rust timings + speedup."""
    cases = _cases()
    print(f"{'operation':24} {'python':>10} {'rust':>10} {'speedup':>9}")
    print("-" * 56)
    speedups = []
    for label, (py_fn, ru_fn) in cases.items():
        py_ns = _median_ns(py_fn)
        ru_ns = _median_ns(ru_fn)
        factor = py_ns / ru_ns if ru_ns else float("inf")
        speedups.append(factor)
        print(f"{label:24} {py_ns / 1000:9.2f}us {ru_ns / 1000:9.2f}us {factor:8.1f}x")
    print("-" * 56)
    print(f"{'geomean speedup':24} {'':>10} {'':>10} {_geomean(speedups):8.1f}x")
    return 0


def _geomean(xs: list[float]) -> float:
    """Geometric mean of the speedup factors."""
    prod = 1.0
    for x in xs:
        prod *= x
    return prod ** (1.0 / len(xs)) if xs else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
