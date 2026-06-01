"""Event-chain compile profile: the Rust EventChain serialization win.

`LiteralVar.create(chain)` now assembles the chain JS in Rust (no per-event
Var-tree composition). This measures the production path across handler counts
and on an event-heavy page, so the win is quantified on real construction.

The Python baseline (the former per-event Var-tree composition) was measured on
this machine class before the cutover and is shown for contrast:

    chain handlers      Python (old)     Rust (now)
    1                   ~153 us          (measured below)
    10                  ~3251 us         (measured below)

Run: ``uv run python scripts/profile_event_chain.py``.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import reflex as rx
from reflex.vars import LiteralVar


class _EvState(rx.State):
    count: int = 0

    def add(self, x: int, y: int) -> None:
        self.count += x + y


def _chain(handlers: int):
    """An on_click EventChain with ``handlers`` add() handlers."""
    on_click = [_EvState.add(i, i) for i in range(handlers)]
    return rx.button("x", on_click=on_click).event_triggers["on_click"]


def event_heavy_page(rows: int = 20):
    """A page of ``rows`` buttons, each with a 3-handler on_click chain."""
    return rx.vstack(
        *(
            rx.button(
                f"Btn {i}",
                on_click=[_EvState.add(i, 1), _EvState.add(i, 2), _EvState.add(i, 3)],
            )
            for i in range(rows)
        )
    )


def _median_us(fn: Callable[[], object], reps: int = 1000) -> float:
    """Median wall-clock microseconds of ``fn`` over ``reps`` runs (warmed)."""
    for _ in range(50):
        fn()
    samples = []
    for _ in range(reps):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    samples.sort()
    return samples[len(samples) // 2] / 1000.0


# Python baseline for LiteralVar.create(chain)._js_expr, measured on this
# machine by checking out the pre-wiring event module (per-event Var-tree
# composition). Re-measure via: `git checkout <pre-wiring> -- event/__init__.py`.
_PY_BASELINE_US = {1: 283.5, 5: 2024.7, 10: 3643.4, 20: 6854.3}


def main() -> int:
    """Profile event-chain creation (Rust) vs the Python baseline."""
    print("--- LiteralVar.create(chain)._js_expr (production = Rust now) ---")
    print(f"{'handlers':>9} {'Rust now':>11} {'Python (old)':>13} {'speedup':>9}")
    for n in (1, 5, 10, 20):
        ch = _chain(n)
        rust = _median_us(lambda ch=ch: LiteralVar.create(ch)._js_expr, reps=500)
        py = _PY_BASELINE_US.get(n)
        sp = f"{py / rust:.0f}x" if py else "-"
        py_s = f"{py:9.1f} us" if py else "        -"
        print(f"{n:9} {rust:8.1f} us {py_s:>13} {sp:>9}")

    rows = 20
    construct = _median_us(lambda: event_heavy_page(rows), reps=200)
    per_chain = _median_us(lambda: LiteralVar.create(_chain(3)), reps=300)
    print(f"\n--- event-heavy page ({rows} buttons x 3-handler chains) ---")
    print(f"  full construction (Rust events)  {construct:8.1f} us")
    print(f"  per 3-handler chain (Rust)        {per_chain:8.1f} us")
    print("  (the old Python composition was the dominant per-page cost)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
