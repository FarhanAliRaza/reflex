# Stage 2 feasibility — handle-based construction (evidence)

Goal (plan §4c-next Stage 2): stop materializing a Python `Component` per
node. `rx.box(...)` hands props to Rust, the node is built in a Rust arena,
and a thin Python **handle** (an arena index) is returned. Construction
moves into Rust; the freeze reads the arena. Python remains only for the
genuinely custom user overrides — the "only user overrides stay Python"
end-state.

This file records what was *measured* (not argued) about whether that
works and where it stops, with backend backward-compatibility as a hard
constraint. Reproduce with `scripts/spike_stage2_construction.py` (probes:
`reflex_compiler_rust._native.spike_push_node` / `spike_node_attr`).

## 1. Construction ceiling — PROVEN ~4–5×

Per-node cost on the docs app (`arena_construction` scope, today's fast path):

| | today | handle floor (store only) |
|---|---|---|
| leaf `rx.text(color=...)` | 14.1 µs | 0.26 µs |
| nested `rx.box(rx.text, padding=)` | 22.9 µs | 0.45 µs |

The floor stores props without parsing; it proves **~11 µs of the 14 µs is
pure Python framing** (`create`→`_create`, `_is_var`, cache lookups, dict
build, descriptors) and is removable. The realistic handle build still does
the literal→Var parsing in Rust (`mirror_props` measures that at ~3 µs), so
the honest construction speedup is **~4–5×**, not the floor ratio.

Construction is ~65% of the 9.4 s page-eval phase, so ~4–5× takes eval
≈9.4 s → ≈5 s, plus the freeze then reads the arena instead of walking
Python objects.

## 2. Mixed trees / override-parents reading handle children — PROVEN cheap

The load-bearing risk: override-parents (DebounceInput reads
`child.event_triggers`; forms collect child refs) and mixed handle+Component
trees require a handle to proxy attribute reads into the arena.

Measured: a proxied read is **0.124 µs** vs 0.039 µs for a native Python
attribute. Override-parents read a handful of child attrs each, so this is
negligible in aggregate. **Mixed trees are feasible.**

## 3. Coverage — PROVEN ~92% of nodes (real 318k-node build)

| class of node | share | disposition |
|---|---|---|
| clean stock (no override, arena-eligible) | 34% | build in Rust, return handle |
| radix (`alias = "RadixThemes"+tag`, class constant) | 45% | registered Rust transform |
| prop-transform overrides (lucide `Icon`, `Stack`, `Link`, triggers) | ~13% | run small Python on the kwargs **dict**, then Rust build |
| control flow (`cond`/`match`/`foreach`) | ~4% | already special-cased in the freeze |
| custom `_post_init`/`style` + node-mutating overrides (debounce/forms) | ~8% | **stay full Python** |

`Icon.create` and the radix override were read directly to confirm the
first two categories operate on the kwargs dict / class constants, not on a
constructed node — so they need no Python `Component` object.

## 4. Backward compatibility — preserved by construction

- The backend/runtime (state, events, API) never builds components under
  the compile scope; `_ARENA_CONSTRUCTION` already gates handles to the
  pipeline. Outside it, construction is byte-for-byte today's `Component`.
- Custom user components (`render`/`add_style`/`_post_init`) keep the full
  Python path.
- Handles are opt-in per eligible class; the ~8% above and everything
  off-pipeline are unchanged.

## 5. What this does NOT yet prove (the real build risk)

- Byte-identical **freeze over a heterogeneous child list** (handles +
  Components). The freeze input model must accept both. Proxy reads being
  cheap (§2) removes the cost objection but not the implementation.
- Parsing props to native IR in `push_node` (the spike stores the dict).
- Per-class registration of the radix/icon/stack transforms into Rust.

Verdict: the approach works and is worth it (~4–5× construction, ~92%
coverage, compat preserved); the remaining work is the freeze's mixed-tree
input model and per-class transform registration, neither blocked by a
measured cost.
