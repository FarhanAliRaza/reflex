"""Profile the Rust compile tail — where time goes inside the Rust pipeline.

The full-compile profile shows the Rust compile tail is ~60% of a page
compile. This breaks that tail into its Rust stages via
``CompilerSession._inner.compile_page_from_arena_profiled`` (gather path), so
the slow stages are visible:

* ``build_snapshot`` — rebuild the IR Snapshot from the wire bundle (PyO3 dict
  extraction of every node + side tables) and run the close pass
  (``subtree_hash`` / hook propagation).
* ``memoize``        — ``memoize_arena_pass`` (dedup subtrees into memo bodies).
* ``emit_page``      — emit the page module JSX.
* ``emit_memo``      — emit each unique memo body's JSX.

Run: ``uv run python scripts/profile_rust_tail.py``.
"""

from __future__ import annotations

import inspect as _inspect
import statistics
import typing as _typing

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


def main() -> int:
    """Profile and print the Rust compile-tail stage breakdown."""
    inner = CompilerSession()._inner
    bundles = [gather_arena(medium_page()) for _ in range(300)]
    for b in bundles[:30]:
        inner.compile_page_from_arena_profiled(b, "Idx", "/")

    agg: dict[str, list[int]] = {}
    for b in bundles:
        _, d = inner.compile_page_from_arena_profiled(b, "Idx", "/")
        for k, v in d.items():
            agg.setdefault(k, []).append(v)

    node_count = len(bundles[0]["nodes"])
    _, memo = CompilerSession()._inner.compile_page_from_arena(
        bundles[0], "Idx", "/", compute_close=True
    )
    print(f"page: {node_count} nodes, {len(memo)} memo bodies\n")

    stages = ["build_snapshot_ns", "memoize_ns", "emit_page_ns", "emit_memo_ns"]
    meds = {k: statistics.median(agg[k]) / 1000 for k in stages}
    total = sum(meds.values())
    print(f"{'Rust stage':18}{'median us':>12}{'share':>9}")
    print("-" * 39)
    for k in stages:
        print(
            f"{k.removesuffix('_ns'):18}{meds[k]:>10.1f}us{meds[k] / total * 100:>8.0f}%"
        )
    print("-" * 39)
    print(f"{'sum':18}{total:>10.1f}us")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
