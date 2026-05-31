# Memoize: full port to Rust IR transform

Goal: eliminate every Python allocation, every redundant tree walk, every
PyO3 boundary crossing the current memoize pipeline performs. Drop the
per-page time on the snakker bench from **26 ms → ≤10 ms** by replacing
`walk_and_memoize` + `create_passthrough_component_memo` + per-memo-body
re-walks with a single in-arena pass that touches each node ≤1 time.

Status as of 2026-05-25: the arena pieces (`Snapshot`, freeze pass,
`memoize_arena_pass`, `emit_jsx_from_snapshot`, `emit_memo_body_jsx`)
exist and have unit tests; they are **not** wired into
`compile_page_from_bytes`. Production still runs Python
`walk_and_memoize` → legacy tree-IR bytes → Rust legacy emit.

---

## 1. Current cost (snakker, 20-iter cProfile)

| Phase | cum ms / 20 iters | per iter | side |
|---|---:|---:|---|
| Python `walk_and_memoize` recursion (excl. `_wrap_with_memo`) | 22 | 1.1 ms | Python |
| `_wrap_with_memo` total | 313 | 15.7 ms | Python |
| ↳ `Component.create` + `_post_init` (wrapper allocation) | 220 | 11.0 ms | Python |
| ↳ `_compute_memo_tag` hash chain | 200 | 10.0 ms | Python |
| `should_memoize` PyO3 calls (1820 × 9.5 µs) | 17 | 0.9 ms | Rust+PyO3 |
| `emit_memo_modules` body pre-walk (`_get_all_hooks` per body) | 117 | 5.9 ms | Python |
| `page_to_ir` msgpack pack | 117 | 5.9 ms | Python |
| `compile_page_from_bytes` (legacy parse + emit) | 60 | 3.0 ms | Rust |
| Pure-Rust emit inside above | 1.7 | 0.085 ms | Rust |

Total per iter: ~26 ms (matches wall clock).

## 2. Target cost (IR-only)

| Phase | per iter | side |
|---|---:|---|
| `freeze_component` (one PyO3 walk, captures everything) | 9–11 ms | Rust+PyO3 |
| `memoize_arena_pass` (single sequential arena scan) | 0.05 ms | pure Rust |
| `emit_jsx_from_snapshot` page emit | 0.05 ms | pure Rust |
| `emit_memo_body_jsx` × N bodies | 0.05 ms | pure Rust |
| File I/O | 0.5 ms | OS |
| **Total** | **~10–12 ms** | — |

Net save: **~14–16 ms / iter ≈ 60% drop**. The remaining ~10 ms is the
irreducible PyO3 cost of reading Python `Component` attributes once.

The IR-only path doesn't add new boundary crossings — `freeze_component`
already walks the tree; the current path walks it three or four times
(`walk_and_memoize`, `_get_all_imports`, `page_to_ir`, per-body
`_get_all_hooks`). Collapsing to one walk is most of the win.

---

## 3. Parity audit — what `_should_memoize` reads vs what the freeze pass captures today

`reflex/compiler/plugins/memoize.py:120` (`_should_memoize`) reads, in
order:

| Input | Source | Captured in `NodeFlags` today? |
|---|---|---|
| `_memoization_mode.disposition == NEVER` | per-class attr | **NO** — freeze does not set `MemoizationDisposition::Never` |
| `isinstance(component, Bare)` | type | YES — `IS_BARE` bit |
| Bare's `contents._get_all_var_data().state / hooks / components-with-state` | Var walk | **NO** — Var-data state/hooks not folded into node flags |
| `tag is None` and not Cond/Match/structural-memo-child | tag, type | partial — `TAG_IS_NONE` bit set; the early-return logic that **skips** memoize for tag-less non-control-flow nodes is not in `should_memoize_arena` |
| `_memoization_mode.disposition == ALWAYS` | per-class attr | **NO** — freeze does not set `Always` |
| Direct vars with state/hooks/embedded-stateful-components | `_get_vars(include_children=False)` | **NO** — captured only as `HAS_STATE_OR_HOOKS` derived from `hooks_internal/hooks_user`, which doesn't catch state read via prop Vars |
| `strategy is SNAPSHOT and not is_snapshot_boundary` (i.e. structural memo child = Foreach) | type, `_memoization_mode.recursive` | **NO** — `IS_SNAPSHOT_BOUNDARY` bit not populated; `IS_STRUCTURAL_MEMO_CHILD` bit reserved but not set |
| `is_snapshot_boundary and _subtree_has_reactive_data` | recursive subtree walk | partial — `PROPAGATES_HOOKS` is computed bottom-up but only from `HAS_STATE_OR_HOOKS`, which is incomplete |

**Conclusion**: today's `should_memoize_arena` would diverge from the
Python predicate on real apps because (a) it doesn't read disposition
overrides, (b) it doesn't see prop-Var reactivity, (c) it doesn't
implement the `tag is None && not Cond/Match/structural` early return.
The unit tests pass because they hand-set the bits.

Before flipping the production path, the freeze pass must populate
every input the predicate consumes. The order below front-loads those
gaps so we never ship a regression.

---

## 4. Implementation phases

Each phase ships a self-contained PR. Tests gate the flip in phase E.

### Phase A — `MemoizationMode` capture in freeze (≈80 LOC, 0 perf impact)

In `freeze.rs:freeze_into_slot`, after `class_name` is read, also read:

```rust
let mode = component.getattr("_memoization_mode")?;
let disposition: String = mode.getattr("disposition")?.getattr("value")?.extract()?;
let recursive: bool = mode.getattr("recursive")?.extract()?;

flags.set_memoization_disposition(match disposition.as_str() {
    "always" => MemoizationDisposition::Always,
    "never"  => MemoizationDisposition::Never,
    _        => MemoizationDisposition::Auto,
});
if !recursive {
    flags.set(NodeFlags::IS_SNAPSHOT_BOUNDARY);
}
```

**Performance**: 2 extra `getattr` + 1 enum compare per node. Per-node
budget ~600 ns × 60 nodes = 36 µs added to freeze. Cache the
`_memoization_mode` `Py<PyType>` lookup on `PyRefs` so the inner
`getattr("disposition")` hits a slot, not a dict. Net: ≤20 µs per page.

**Tests**: extend `freeze` unit test to assert
`flags.memoization_disposition()` round-trips for components with each
disposition; assert `IS_SNAPSHOT_BOUNDARY` set for an
`Upload`-style component.

### Phase B — structural-memo-child + reactive-var capture (≈150 LOC, +60 µs/page)

1. **`IS_STRUCTURAL_MEMO_CHILD` bit**: `freeze_into_slot` checks
   `class_name == "Foreach"` (already known — kind is also `Foreach`).
   One AND + comparison; effectively free.

2. **Reactive prop-Var detection**: the existing `read_rendered_props`
   loop already iterates the component's render output via `_render`
   and collects `(name, js_expr)` pairs. Extend it: for each Var it
   sees, call `var._get_all_var_data()` once, inspect
   `var_data.state` / `var_data.hooks` / `var_data.components`. If
   any are non-empty, set `HAS_STATE_OR_HOOKS`.

   **The key win**: this read happens **inside the existing prop
   loop**, so it costs one extra method call per Var the loop is
   already touching. `_get_all_var_data` is `@functools.cache`-decorated
   on the Var instance, so per-Var overhead is one PyO3 `call_method0` +
   four attribute reads = ~1 µs. Snakker has ~10 reactive Vars across
   4 pages = +10 µs / iter total.

3. **Embedded-Component reactivity**: `var_data.components` is a list
   of Component instances embedded in a Var's value. The Python
   predicate recursively walks those for reactive data. The freeze
   pass already visits every Component in the page tree, so this
   recursion is **already paid for**. The freeze just needs to track
   "did any prop-Var component-list intersect a node already marked
   reactive?" via a `HashSet<usize>` keyed on `id(component)`. Set
   the bit retroactively in the close pass.

   This is the only spot that adds bookkeeping. Budget: HashSet of
   60 ints, lookup is amortized 10 ns × 60 nodes = 600 ns. Free.

4. **Bare-contents reactivity**: when `class_name == "Bare"`,
   `read_rendered_props` doesn't run (Bare has no tag). Add a Bare-
   specific branch that reads `component.contents._get_all_var_data()`
   and applies step 2's logic to that single Var.

**Tests**: add fixtures for (a) Foreach child, (b) Component with
state-reading prop Var, (c) Bare wrapping a state-reading Var,
(d) Component with prop-Var containing a Component that reads state.

### Phase C — correct `should_memoize_arena` (≈40 LOC, +5 ns/node)

Replace `memoize_arena.rs` body with the full Python parity logic:

```rust
pub fn should_memoize_arena(snap: &Snapshot, idx: NodeIdx) -> bool {
    let n = snap.node(idx);
    let f = n.flags;

    // Disposition NEVER / ALWAYS short-circuit before anything else.
    match f.memoization_disposition() {
        MemoizationDisposition::Never  => return false,
        MemoizationDisposition::Always => return true,
        MemoizationDisposition::Auto   => {}
    }

    // Bare: state/hooks in contents Var → memoize.
    if f.contains(NodeFlags::IS_BARE) {
        return f.contains(NodeFlags::HAS_STATE_OR_HOOKS);
    }

    // Tag-less, non-control-flow, non-structural-memo-child → skip.
    if f.contains(NodeFlags::TAG_IS_NONE)
        && !matches!(n.kind, NodeKind::Cond | NodeKind::Match)
        && !f.contains(NodeFlags::IS_STRUCTURAL_MEMO_CHILD) {
        return false;
    }

    // Direct prop-Var reactivity OR snapshot-boundary with reactive subtree.
    let has_direct = f.contains(NodeFlags::HAS_STATE_OR_HOOKS)
                  || f.contains(NodeFlags::HAS_EVENT_TRIGGERS);
    let snapshot_with_reactive_descendants =
        f.contains(NodeFlags::IS_SNAPSHOT_BOUNDARY)
        && f.contains(NodeFlags::PROPAGATES_HOOKS);
    let strategy_snapshot_non_boundary =
        f.contains(NodeFlags::IS_STRUCTURAL_MEMO_CHILD)
        && !f.contains(NodeFlags::IS_SNAPSHOT_BOUNDARY);

    has_direct || snapshot_with_reactive_descendants || strategy_snapshot_non_boundary
}
```

Per-node cost: 8 bit-tests, one enum match. ~15 ns. For 60 nodes,
~1 µs per page. Hot loop is sequential `nodes` iteration — perfect
prefetch.

**Tests**: build a parity harness — run Python `_should_memoize` AND
`should_memoize_arena` on every node of every page in the docs app
and snakker. Fail on mismatch. This becomes a CI guard.

### Phase D — wrap-redirect production wiring (≈200 LOC, the actual cut-over)

New entry point on `CompilerSession`:

```rust
#[pyo3(signature = (component, route, title=None, meta=None, ...))]
fn compile_page_from_component_arena(
    &self,
    py: Python<'_>,
    component: &Bound<'_, PyAny>,
    route: &str,
    ...
) -> PyResult<(String, Vec<(Symbol, Symbol)>, Vec<MemoBodyOut>)> {
    let refs = self.refs.borrow(py);
    let mut snap = freeze_component(py, component, &refs)?;
    py.allow_threads(move || {
        memoize_arena_pass(&mut snap);
        let mut page_buf = CodeBuffer::with_capacity(4096);
        emit_jsx_from_snapshot(&mut page_buf, &snap);
        // Emit one buffer per memo body, keyed by name.
        let bodies: Vec<MemoBodyOut> = snap.memo_bodies.iter().map(|b| {
            let mut buf = CodeBuffer::with_capacity(2048);
            emit_memo_body_jsx(&mut buf, &snap, b.root);
            MemoBodyOut { name: resolve_unchecked(b.name).to_owned(), js: buf.into_string() }
        }).collect();
        let imports = harvest_imports(&snap);  // from existing harvest.rs
        Ok((page_buf.into_string(), imports, bodies))
    })
}
```

**Python side** (in `reflex/compiler/rust_pipeline.py`, replace the
~50-line per-page block from line 184 onward with):

```python
page_js, imports, memo_bodies = sess.compile_page_from_component_arena(
    component, route, title=None, meta=None,
)
sess.collect_all_imports_into(all_imports, component)
out_path = Path(compiler_utils.get_page_path(route))
out_path.write_text(page_js)
for body in memo_bodies:
    body_path = components_dir / f"{body.name}.jsx"
    body_path.write_text(body.js)
```

Things deleted from this code path:
- `walk_and_memoize` call (and the entire `rust_memo.py` module
  except `_signature_for` until phase E).
- `compile_unevaluated_page` → still needed (user page callable
  execution); kept as-is.
- `_get_all_custom_code` / `_get_all_hooks` per-page render: moved
  into the freeze pass's per-node harvest.
- `page_to_ir` msgpack pack: replaced by the in-memory Snapshot.
- `emit_memo_modules` loop: replaced by `memo_bodies` from above.

**Behind a feature flag** for one PR: env var
`REFLEX_RUST_ARENA_PAGES=1` selects the new path; default off until
the parity harness is green on docs app + snakker.

**Performance accounting**:

| Operation | Before | After | Δ |
|---|---:|---:|---:|
| Python `walk_and_memoize` | 1.1 ms | 0 | −1.1 |
| Python wrapper allocation | 11.0 ms | 0 | −11.0 |
| Python `_compute_memo_tag` | 10.0 ms | 0 | −10.0 |
| Python `page_to_ir` pack | 5.9 ms | 0 | −5.9 |
| Python `emit_memo_modules` body pre-walk | 5.9 ms | 0 | −5.9 |
| Rust `parse_page` (legacy tree-IR) | 1.2 ms | 0 | −1.2 |
| `should_memoize` PyO3 calls | 0.9 ms | 0 | −0.9 |
| **freeze_component (PyO3)** | 0 | 9–11 | +10 |
| `memoize_arena_pass` | 0 | 0.05 | +0.05 |
| `emit_jsx_from_snapshot` | 0 | 0.05 | +0.05 |
| `emit_memo_body_jsx` × N | 0 | 0.05 | +0.05 |

Net: −24 ms before, +10 ms after = **−14 ms / page**. On snakker
(4 pages) that's **−56 ms / iter ≈ −78%** on the per-page part, or
**~−45%** including the per-compile constant overhead. The 0.05 ms
numbers come from the existing unit tests in `memoize_pass.rs` and
`page_from_snapshot.rs`.

### Phase E — kill the Python wrapper path (≈−800 LOC)

Once the parity harness has been green for one cycle:

1. Delete `reflex/compiler/rust_memo.py` entirely (the
   `walk_and_memoize`/`emit_memo_modules` driver).
2. Delete the `_wrap_with_memo` / `create_passthrough_component_memo`
   call sites in `reflex/experimental/memo.py`. Leave the
   `ExperimentalMemoComponent` class for user-facing `@rx._x.memo`,
   but its compile-time consumption goes through the IR.
3. Delete `compile_page_from_bytes` / `compile_memo_from_bytes`
   PyO3 methods on `CompilerSession` (they were the bridge from
   msgpack tree-IR → legacy emit; nothing calls them after Phase D).
4. Delete `reflex/compiler/ir/bridge.py:page_to_ir`, the entire
   `reflex/compiler/ir/{schema,pack,canonical}.py` module, and the
   msgpack dependency.
5. Delete the legacy tree-IR `parse_page` / `emit_page` in
   `reflex-compiler-rust` (`reflex_db`, `reflex_codegen::page`,
   `reflex_ir::parse`). The arena `Snapshot` is the only IR.

This is bulk deletion, no behavior change. Run the existing diff
harness (`scripts/diff_legacy_vs_rust.py`) on the docs app — output
must be byte-identical to phase D's output.

---

## 5. Micro-optimizations inside the arena pass (cycle hunting)

Each one is small in isolation; together they keep the
pure-Rust hot loop under 100 µs/page.

### 5.1 `collect_memo_candidates` Vec sizing

```rust
let cap = snapshot.nodes.len() >> 3;  // ~12.5% candidate rate empirically
let mut bodies = Vec::with_capacity(cap);
let mut dedup = HashMap::with_capacity(cap);
```

Saves ~3 amortized realloc/grow cycles on a 60-candidate page. ~200 ns.

### 5.2 Single-pass candidate collection + wrapper insertion

The current `memoize_arena_pass` walks `0..nodes.len()` **three times**:
once in `collect_memo_candidates`, again in `insert_memo_wrappers`,
and again in `rewrite_memo_event_triggers`. Three sequential scans of
60 × 256-byte nodes = 45 KB read 3×. Cache hot on L1 (32 KB) but
borderline.

Fuse into one walk:

```rust
pub fn memoize_arena_pass(snap: &mut Snapshot) -> usize {
    let n_initial = snap.nodes.len();
    let cap = n_initial >> 3;
    snap.memo_bodies.reserve(cap);
    snap.memo_dedup.reserve(cap);
    snap.wrap_redirects.reserve(cap);

    for idx in 0..n_initial as NodeIdx {
        if !should_memoize_arena(snap, idx) { continue; }

        let (hash, children) = {
            let n = snap.node(idx);
            (n.subtree_hash, n.children.clone())
        };

        let body_slot = *snap.memo_dedup.entry(hash).or_insert_with(|| {
            let style = snap.node(idx).style_key;
            let name = derive_memo_name(style, hash);
            let slot = snap.memo_bodies.len() as u32;
            snap.memo_bodies.push(MemoizeBody {
                name, root: idx, subtree_hash: hash,
                signature: intern_passthrough_or_snapshot(snap.node(idx).flags),
            });
            slot
        });
        let body_name = snap.memo_bodies[body_slot as usize].name;

        let wrapper_idx = snap.nodes.len() as NodeIdx;
        let mut wrapper = NodeSnapshot::default();
        wrapper.kind = NodeKind::MemoizeWrapper;
        wrapper.tag = body_name;
        wrapper.subtree_hash = hash;
        wrapper.children = children;
        wrapper.flags.set(NodeFlags::PROPAGATES_HOOKS);
        snap.nodes.push(wrapper);
        snap.wrap_redirects.insert(idx, wrapper_idx);

        rewrite_one_node_event_triggers(snap, idx);
    }
    snap.memo_bodies.len()
}
```

Saves 2 × 60 × 256-byte scans = 30 KB read. Practical impact: ~10 µs.

### 5.3 `derive_memo_name` — stack-allocate the name

`format!("{subtree_hash:016x}")` heap-allocates a 16-byte string each
call. Replace with `write!(name, "{:016x}", hash)` directly into the
existing `String name` buffer.

Saves 1 allocation × 60 candidates × ~80 ns = 5 µs.

### 5.4 `rewrite_one_node_event_triggers` — in-place rewrite

Currently builds a new `SmallVec` of callbacks and a new `SmallVec`
of hooks, then swaps. For ≤2 callbacks (the SmallVec inline arity)
this is stack churn but not allocation. Either keep as-is, or rewrite
in place with `node.event_callbacks.iter_mut()` + a parallel
`hooks_user.push` loop. Save: ~30 ns × 16 triggers = 0.5 µs. Skip
unless 5.1–5.3 leave room on the budget.

### 5.5 `xxh3_64` over the canonical bytes — vectorize

`subtree_hash` is computed during `SnapshotBuilder::finish`. Profile
shows the hash itself is ~15% of close-pass time on the docs app.
`xxhash_rust::xxh3` already uses SSE2; check that release builds
inline the 64-byte-block-at-a-time loop (Cargo `target-cpu=native`
or at least `+sse4.2` in the bench profile). Saves nothing on x86_64
default builds; ~30% on the close pass on ARM.

### 5.6 Inline `should_memoize_arena`

Mark `#[inline]`. The fused loop above calls it once per node; the
function is 8 bit-tests + 1 match. LLVM will inline regardless, but
flagging it removes any doubt and lets the disposition match collapse
to a jump table inside the call site.

### 5.7 `event_callback_overrides` map preallocation

`Snapshot::event_callback_overrides` is currently lazy-default. When
the memo-body emit fires `rewrite_memo_body_event_triggers`, every
trigger inserts. Reserve once at the top of `memoize_arena_pass`:

```rust
let trigger_total: usize = snap.nodes.iter()
    .filter(|n| should_memoize_arena(...)) // skip — already walking
    .map(|n| n.event_callbacks.len())
    .sum();
snap.event_callback_overrides.reserve(trigger_total);
```

In the fused single-pass version, do this during the walk (track a
running total). One HashMap grow saved.

### 5.8 `node_pyids` skipped on the hot path

The freeze pass populates `node_pyids: Vec<usize>` per node for
hypothetical Python round-trips. Memoize pass doesn't read it.
Verify it's only populated when needed; if always built, gate behind
a flag — saves a `Vec::push` × N nodes ≈ 60 × 30 ns = 1.8 µs.

---

## 6. The freeze-pass cost ceiling

Everything downstream is sub-100 µs. The dominant cost is freeze.
Today's pyread cost from `PROFILING_FINDINGS.md` §7 (177 nodes):

```
read_var_data_ns / var       15,415 ns   ← #1 cost
prop_value_getattr_ns           184 ns / prop
isinstance_var_ns                 6 ns / prop
```

For freeze to fit the 9–11 ms/page budget on a snakker page
(~50 nodes, ~30 vars, ~250 props), it has to stay under:

- 50 nodes × ~180 µs/node = 9 ms ← already where read_page is.

Two freeze-specific levers beyond the existing read_page work:

**(F1) Memoize-mode + recursive read shares the per-class lookup**.
The first time freeze sees a Component class, cache
`(disposition, recursive)` on `PyRefs` keyed by `type(c) as *const _`.
Every subsequent same-class node reads the tuple from a `HashMap<usize,
(u8, bool)>` instead of a `getattr` chain. Saves ~500 ns × 50 nodes =
25 µs/page after the first instance.

**(F2) Var data is read once per Var across the page**. `_get_all_var_data`
is `@functools.cache`-decorated, so repeated Python-side calls are
cheap. The PyO3 side pays the call_method0 boundary each time though.
A small per-page `HashMap<*const PyVar, VarDataSummary>` short-circuits
duplicate reads. Saves 5+ µs/page when state vars are read by multiple
nodes (typical).

These don't have to land with this work; they're freeze-side wins
independent of memoize.

---

## 7. Test strategy

### 7.1 Parity unit tests (per phase)

- Phase A: round-trip each `MemoizationDisposition` value through freeze; assert `IS_SNAPSHOT_BOUNDARY` set for a hand-built `Upload`.
- Phase B: 4 fixtures listed above.
- Phase C: parity oracle — `_should_memoize(py_comp) == should_memoize_arena(snap, idx)` for every node of every page in `tests/integration/test_app/` plus snakker plus docs app. Run as a CI job.
- Phase D: byte-exact diff between legacy and new emit on the docs app via the existing `scripts/diff_legacy_vs_rust.py`.

### 7.2 Performance regression test

Add `tests/benchmarks/test_memoize_pass.py`:

```python
def test_memoize_pass_under_100us(snakker_page):
    snap = freeze_component(snakker_page)
    t0 = time.perf_counter_ns()
    for _ in range(1000):
        memoize_arena_pass(snap.clone())
    elapsed = (time.perf_counter_ns() - t0) / 1000
    assert elapsed < 100_000  # 100 µs hard ceiling
```

Run on every PR via `pytest tests/benchmarks/test_memoize_pass.py -m bench`.

### 7.3 End-to-end wall-clock

Re-run the snakker py-spy + cProfile after Phase D. Target: median
iter time ≤12 ms (down from 26 ms). Document in `PROFILING_FINDINGS.md`
under a new "§13 — Memoize Rust cut-over" section.

---

## 8. Order of operations (one PR per phase)

1. **PR1** — Phase A. ~80 LOC freeze.rs, 3 unit tests.
2. **PR2** — Phase B. ~150 LOC freeze.rs + new helpers in pyo3_reader, 6 unit tests.
3. **PR3** — Phase C + parity harness. ~40 LOC memoize_arena.rs, parity test infra.
4. **PR4** — Phase D. New `compile_page_from_component_arena` method, behind env flag, plus rust_pipeline.py change. Diff-harness green required to merge.
5. **PR5** — Flip the env flag default. Watch CI for 1 week.
6. **PR6** — Phase E. Bulk deletion of Python memoize, msgpack bridge, legacy tree IR.

Total estimated ship time: 6 small PRs, 2 weeks of focused work.
Total LOC delta: roughly **+500 Rust, −1300 Python** = **net −800
LOC**.

---

## 9. What this plan does NOT cover

- **App-root emit through the same arena path**: currently `_app_root`
  composition (radix wrap, theme wrap, toaster) is Python +
  `compile_app_root_module` Rust template. That's a separate ~4 ms
  one-time-per-compile cost. Worth porting next; out of scope here.
- **`_get_frontend_packages` / `bun install`**: still pulls from the
  merged `all_imports` dict on the Python side. The freeze pass
  already populates per-node `imports`; the only Python-side residue
  is the cross-page union, which is a few hundred µs and benign.
- **Custom-component (`@rx.memo`) compile**: today
  `_compile_memo_components` runs the legacy plugin chain for user
  `@rx.memo` definitions. The IR transform handles auto-memoization;
  user `@rx.memo` is a separate code path that lands later.
