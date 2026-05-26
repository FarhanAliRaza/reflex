"""Plan PR7: the freeze pass must populate ``Snapshot.var_data`` with
deduplicated entries — every unique Python ``Var`` produces one record,
and every node that references that Var stores the same index in its
``vars_used`` slot.

Verified through ``CompilerSession.snapshot_stats(component)`` which
returns a dict with:

* ``node_count``      — total nodes pushed by freeze.
* ``var_data_len``    — entries in ``Snapshot.var_data`` (after dedup).
* ``vars_used_total`` — sum of per-node ``vars_used`` ref counts (i.e.
  number of (node, var) edges).
* ``unique_var_ids``  — count of distinct ``id(var)`` observed.

Dedup invariant: ``var_data_len == unique_var_ids``. Without dedup the
length would equal ``vars_used_total`` (one entry per reference).
"""

from __future__ import annotations

import reflex as rx
from reflex.compiler.session import CompilerSession


class _DedupState(rx.State):
    counter: int = 0


def test_var_data_deduped_when_same_var_used_in_multiple_nodes() -> None:
    sess = CompilerSession()
    # Three nodes all reading the same `counter` Var — dedup should
    # produce one var_data entry referenced from each node.
    comp = rx.vstack(
        rx.text(f"a={_DedupState.counter}"),
        rx.text(f"b={_DedupState.counter}"),
        rx.text(f"c={_DedupState.counter}"),
    )
    stats = sess.snapshot_stats(comp)
    assert stats["unique_var_ids"] >= 1, stats
    assert stats["var_data_len"] == stats["unique_var_ids"], (
        f"var_data not deduped: len={stats['var_data_len']}, "
        f"uniques={stats['unique_var_ids']}"
    )
    # Multiple nodes referenced the same Var → at least 2 edges.
    assert stats["vars_used_total"] >= stats["var_data_len"], stats


def test_var_data_empty_when_no_reactive_vars() -> None:
    sess = CompilerSession()
    comp = rx.vstack(rx.text("static a"), rx.text("static b"))
    stats = sess.snapshot_stats(comp)
    assert stats["var_data_len"] == 0
    assert stats["vars_used_total"] == 0


def test_var_data_dedup_across_repeated_subtree() -> None:
    sess = CompilerSession()
    # Same Var threaded through two structurally identical subtrees.
    sub = rx.text(f"x={_DedupState.counter}")
    comp = rx.vstack(sub, sub)
    stats = sess.snapshot_stats(comp)
    assert stats["var_data_len"] == 1, stats
