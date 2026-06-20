"""Stage 2 feasibility spike: handle-based construction (reproducible proof).

Answers, with numbers, whether component construction can move into Rust
behind a thin Python handle (plan §4c-next Stage 2) and whether the
backward-compat-critical operation — an override-parent reading a handle
child's attributes — stays cheap.

Probes live in ``reflex_compiler_rust._native`` (``spike_push_node`` /
``spike_node_attr`` / ``spike_reset``). NOT wired into the pipeline; this
measures the primitives in isolation.

Run: ``uv run --no-sync python scripts/spike_stage2_construction.py``
"""
# ruff: noqa: E402, T201, ANN001 — standalone spike script (compat shim
# before imports, prints results to stdout).

from __future__ import annotations

import inspect as _inspect
import time
import typing as _typing

_orig = _typing._eval_type  # Python 3.14 / pydantic compat shim
_params = _inspect.signature(_orig).parameters
if "prefer_fwd_module" not in _params:

    def _eval_type_compat(*a, **k):
        return _orig(*a, **{x: v for x, v in k.items() if x in _params})

    _typing._eval_type = _eval_type_compat

from reflex_base.components.component import arena_construction
from reflex_compiler_rust._native import (  # type: ignore[attr-defined]
    spike_node_attr,
    spike_push_node,
    spike_reset,
)

import reflex as rx


def _bench(fn, n: int = 100000) -> float:
    fn()
    t = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n * 1e6


class _Handle:
    """The thin per-node handle: an arena index, attribute reads proxied."""

    __slots__ = ("_arena_idx",)

    def __init__(self, idx: int):
        self._arena_idx = idx

    def __getattr__(self, name: str):
        return spike_node_attr(self._arena_idx, name)


def main() -> None:
    """Print the construction-cost and proxy-read measurements."""
    with arena_construction():
        today_leaf = _bench(lambda: rx.text("hi", color="red"))
        today_nested = _bench(
            lambda: rx.box(rx.text("hi", color="red"), padding="4px"), n=40000
        )

    def build_leaf():
        spike_reset()
        return _Handle(spike_push_node("p", {"color": "red"}, []))

    def build_nested():
        spike_reset()
        child = spike_push_node("p", {"color": "red"}, [])
        return _Handle(spike_push_node("div", {"padding": "4px"}, [child]))

    handle_leaf = _bench(build_leaf)
    handle_nested = _bench(build_nested, n=40000)

    spike_reset()
    idx = spike_push_node("button", {"on_click": "X", "style": "Y"}, [])
    read_proxy = _bench(lambda: spike_node_attr(idx, "on_click"))
    with arena_construction():
        comp = rx.button("b", color="red")
    read_today = _bench(lambda: comp.style)

    print(
        f"leaf   construct  today {today_leaf:6.2f}us  handle-floor {handle_leaf:6.2f}us"
    )
    print(
        f"nested construct  today {today_nested:6.2f}us  handle-floor {handle_nested:6.2f}us"
    )
    print(
        f"proxy attr read   handle->arena {read_proxy:.3f}us  vs component.attr {read_today:.3f}us"
    )
    print(
        "NOTE: handle-floor stores props only; realistic build adds Rust "
        "prop-parse (~3us, the mirror_props cost) -> ~4-5x, not the floor ratio."
    )


if __name__ == "__main__":
    main()
