# Plan — Implement rust_port_inventory.md (freeze pass + 16 walks)

## Context

The legacy mechanical compile costs ~13.6 ms/page (median, 165-node synthetic),
dominated by `Component.render()` (8.94 ms, 66%) and `_get_all_imports`
(2.68 ms). `reflex run-rust` already shaves ~9.9 ms/page (44%) by routing
through a partial Rust pipeline (`reflex_pyread` → `reflex_codegen`), but walks
1, 3–8, and 10–16 are still in Python and the Rust IR is a *tree*
(`reflex_ir::Component<'a>`), not the flat arena the inventory specifies. The
goal is to deliver the freeze pass + flat `NodeSnapshot` arena described in
`rust_port_inventory.md` and port all 16 walks to Rust, evolving (not
duplicating) the existing IR. The qualitative payoff isn't just the ~12 ms/page
cold-compile saving — it's making hot-reload cost linear in the diff, not in
the app, via subtree-hash caching.

User decisions (locked):
- **Evolve `reflex_ir` in place** — replace `Component<'a>` tree with flat
  `Snapshot`; rewrite `reflex_codegen` + `reflex_semantic` to read it.
- **All 16 walks in scope** — staged rollout, not big-bang.
- **Python orchestrates freeze**; Rust appends nodes via PyO3. No
  Rust→Python callbacks inside walks.

## Design decisions

### IR schema (lives in `reflex_ir`, not a new crate)

```rust
struct NodeSnapshot {            // ~one cache line for the hot fields
    kind: NodeKind,              // u8: Element/Text/Foreach/Cond/Match/Memoize/Fragment/Expr/MemoizeWrapper
    tag: Option<Symbol>,
    style_key: Symbol,           // type(self).__qualname__
    style: Symbol,               // pre-rendered emotion JS
    rendered_props: SmallVec<[(Symbol, Symbol); 4]>,
    event_callbacks: SmallVec<[(Symbol, Symbol); 2]>,
    imports: SmallVec<[ImportEntry; 4]>,
    hooks_internal: SmallVec<[HookEntry; 2]>,
    hooks_user: SmallVec<[HookEntry; 1]>,
    custom_code: Option<Symbol>,
    dynamic_imports: SmallVec<[Symbol; 1]>,
    ref_name: Option<Symbol>,
    vars_used: SmallVec<[VarDataRef; 4]>,
    children: Range<u32>,        // indices into snapshot.nodes
    flags: NodeFlags,            // u16, bit-packed (see below)
    subtree_hash: u64,           // xxh3_64, filled at freeze close
}

struct Snapshot {
    nodes: Vec<NodeSnapshot>,
    memo_bodies: Vec<MemoizeBody>,
    memo_dedup: HashMap<u64, u32>,         // subtree_hash → memo_bodies idx
    var_data: Vec<VarDataEntry>,           // referenced by VarDataRef(u32)
    var_hooks: Vec<Symbol>,                // backing Range<u32> in VarDataEntry
    var_imports: Vec<(Symbol, Symbol)>,
    var_deps: Vec<Symbol>,
    var_components: Vec<Symbol>,
    control_flow: ControlFlowExtras,       // sparse side maps keyed by NodeId
    source_locs: Vec<SourceLoc>,           // optional, indexed by NodeId; off by default
    app_wraps: Vec<(i32, Symbol, NodeId)>, // (sort_key, name, root_arena_idx) — deduped
    add_custom_code_extra: HashMap<NodeId, SmallVec<[Symbol; 2]>>,
    special_props: HashMap<NodeId, SmallVec<[Symbol; 1]>>,
    rename_props: HashMap<NodeId, SmallVec<[(Symbol, Symbol); 1]>>,
    app_style_map: HashMap<Symbol, Symbol>, // class qualname → rendered emotion JS
    root: u32,
    page_meta: PageMeta,                    // route, title, meta, schema_version
}
```

Rationale:
- `Vec<NodeSnapshot>`, not bumpalo — `SmallVec` isn't `Copy`, so bumpalo's
  `alloc<T: Copy>` rejects it; `Vec` is fine and removes the `'arena` lifetime
  from public types.
- Hot fields stay inline; cold/rare fields (`app_wraps`,
  `add_custom_code_extra`, `special_props`, `rename_props`) move to side
  HashMaps keyed by NodeId since >99% of nodes don't carry them.
- Control-flow payloads (`Cond.test`, `Foreach.iter`, `Match.arms`,
  `Expr.value`, `Memoize.key`) are sparse — keep them in
  `ControlFlowExtras`, not as enum payload bloat on every node.
- `Value`, `EventHandler`, `Hook` are **deleted from public IR**. Vars are
  pre-rendered to a `Symbol` (the JS expression) at freeze time;
  `VarData` (hooks/imports/state/deps/components/position) goes into
  the side `var_data` table and is referenced by `VarDataRef(u32)`.

### NodeFlags layout (u16)

```
bit 0: has_state_or_hooks       bit 5-6: memoization_disposition (00=AUTO, 01=NEVER, 10=ALWAYS)
bit 1: has_event_triggers       bit 7:   is_structural_memo_child
bit 2: is_bare                  bit 8:   tag_is_none
bit 3: is_snapshot_boundary     bit 9-15: reserved
bit 4: propagates_hooks (computed bottom-up at freeze close)
```

### Freeze contract

- One PyO3 call per Component (mirrors today's `reflex_pyread::read_page`).
- Per-Component methods called exactly **once**: `_get_imports`,
  `_get_hooks_internal`, `_get_hooks`, `_get_added_hooks`, `_get_custom_code`,
  `_get_dynamic_imports`, `_get_app_wrap_components`, `_get_style` →
  `format_as_emotion`, `_render` (props pack), `get_ref`, event_triggers
  iteration with `LiteralVar.create`.
- Observation-only. `REFLEX_DEBUG_FREEZE=1` asserts no Component mutation
  occurred during freeze.
- After freeze close (single bottom-up arena sweep): fill `propagates_hooks`
  and `subtree_hash`.

## Stages

Each stage ships behind a feature flag, runs alongside legacy under the diff
harness, and has both correctness and perf gates. Stages can interleave PRs
but cannot ship the perf flag default-on until the previous stage's flag is.

### Stage 0 — Schema + no-op freeze skeleton

- Add `smallvec`, `xxhash-rust` (xxh3) to `crates/reflex_ir/Cargo.toml`.
- New `crates/reflex_ir/src/snapshot/{mod.rs, node.rs, flags.rs, kinds.rs,
  tables.rs, builder.rs}`. Legacy `Component<'a>`, `Value<'a>`, `parse.rs`,
  `visitor.rs` move under a `legacy` submodule gated by
  `feature = "legacy-tree-ir"` (default-on).
- New `crates/reflex_pyread/src/freeze.rs` — `freeze_component(py, root,
  refs) -> Snapshot`. Fills `kind`, `tag`, `style_key`, `children`,
  placeholder `subtree_hash`. All other fields empty. Caches `id(component)
  → NodeId` on a session-scoped map.
- New PyO3 binding `CompilerSession.freeze_page(component)` in
  `crates/reflex_py/src/session.rs`.
- `reflex/compiler/rust_pipeline.py`: under `REFLEX_FREEZE_SHADOW=1`, call
  `sess.freeze_page(component)` and discard. Default path unchanged.
- `scripts/diff_legacy_vs_rust.py`: add `--stage=N` flag that composes the
  per-stage env vars.

**Gate:** `REFLEX_FREEZE_SHADOW=1 uv run reflex run-rust --frontend-only`
runs to completion on `docs/app` and `examples/rust_compiler_demo`. Freeze
adds <5% wall time per `scripts/benchmark_stages.py`. Sanity-test:
`size_of::<NodeSnapshot>()` ≤ 256 bytes.

### Stage 1 — Read-only harvests (walks 2, 4, 5, 7)

- Freeze fills `imports`, `custom_code`, `add_custom_code_extra`,
  `dynamic_imports`, `ref_name`. Pre-existing `reflex_pyread/src/imports.rs`
  becomes an arena reader; `_get_imports` per node still runs in Python at
  freeze time.
- New walks in `crates/reflex_codegen/src/harvest.rs`:
  `collect_imports`, `collect_custom_code`, `collect_dynamic_imports`,
  `collect_refs`. All bottom-up arena traversals, no PyO3.
- `rust_pipeline.compile_pages`: under `REFLEX_RUST_HARVEST=1`, page-level
  aggregates come from arena walks; default path keeps Python.

**Gate:** zero byte diffs in JSX `import {…}` blocks, dynamic-import lines,
and custom-code blocks across the corpus (`docs/app`, 5 example apps,
200-route synthetic). Combined harvest <0.5 ms/page (vs 2.82 ms today).

### Stage 2 — Format passes (walks 3, 14, 15)

- Freeze fills `hooks_internal`, `hooks_user` per node.
- New `crates/reflex_codegen/src/hooks.rs::render_hooks` — position-sorts
  and joins. Replaces `reflex_base.compiler.templates._render_hooks`.
- New `crates/reflex_codegen/src/imports_emit.rs` — sort + dedupe + format
  arena imports. Replaces `reflex/compiler/utils.py::compile_imports`.
- Under `REFLEX_RUST_FORMAT=1`, `rust_pipeline.compile_pages` swaps both.

**Gate:** byte-identical hook blocks and import blocks across corpus.
Combined format <0.05 ms/page.

### Stage 3 — Flags + subtree hash (walks 8, 9)

- Freeze close pass fills `flags` (all bits) and real
  `subtree_hash = xxh3_64(kind, tag, rendered_props, style, event_callbacks,
  hooks_*, custom_code, children's subtree_hash)`.
- `should_memoize_arena(snapshot, node_id)` becomes a single bit-test.
- Under `REFLEX_RUST_PREDICATE=1`, `session.should_memoize(component)`
  resolves component → NodeId via session map, then bit-tests.
- Under `REFLEX_DEBUG_FREEZE=1`: per-call assertion that the arena
  predicate matches the legacy `_should_memoize` decision.

**Gate:** zero predicate disagreements across corpus. Memoize-decision
phase <0.05 ms/page (was 0.52 ms).

### Stage 4 — Render emit (walks 1, 13)

- Freeze fills `rendered_props`, `event_callbacks`, `style`, `special_props`,
  `rename_props`, `vars_used`. Heavy lifting: per-node `_render()`,
  `_get_style()` → `format_as_emotion`, `event_triggers` iteration,
  `LiteralVar.create()`, and prop name camelCasing all happen at freeze
  time. Codegen becomes "write the Symbol's resolved string."
- Port `format_as_emotion` (Python `style.py`) to Rust string format.
- New `crates/reflex_codegen/src/page.rs::emit_jsx_from_snapshot` walks
  arena depth-first emitting JSX.
- Under `REFLEX_RUST_RENDER=1`, `CompilerSession.compile_page_from_component`
  internally does `freeze → emit_jsx_from_snapshot`.
- Add `parity_codegen.rs` test: for each fixture page, assert
  `emit_page(legacy_tree)` byte-equals `emit_page_from_snapshot(freeze)`.

**Gate:** zero diffs in `.web/app/routes/*.jsx` body content across corpus.
Render phase <0.8 ms/page (was 8.94 ms; ≥10× speedup).

### Stage 5 — Style merge + app-wrap (walks 6, 12)

- Split `reflex/compiler/compiler.py::compile_unevaluated_page` into two
  variants. New `compile_unevaluated_page_no_style(route, page, theme)`
  skips the `_add_style_recursive` call (which mutates Components
  pre-freeze today).
- Freeze accepts `app_style_map: dict[str, Style]` as input, populates
  unmerged `style` per node, then `crates/reflex_codegen/src/style.rs::
  merge_app_styles(&mut snapshot)` runs as a Rust arena pass:
  defaults → app-style → theme → instance, exactly matching Python's order.
- App-wrap subtree handling: freeze walks `_get_app_wrap_components()`
  results recursively, **appends wrapper subtrees as their own arena
  nodes**, and records `(sort_key, name, NodeId)` in `snapshot.app_wraps`
  deduped by `(sort_key, name)`. `rust_pipeline.compile_pages` reads
  `snapshot.app_wraps` instead of calling
  `component._get_all_app_wrap_components()`.
- Under `REFLEX_RUST_STYLE_MERGE=1`. `_add_style_recursive` stays on
  `Component` (additive rule); it just isn't called from the compiler.
- `REFLEX_DEBUG_FREEZE=1` asserts merged arena style equals legacy
  `_get_style()` output per node.

**Gate:** zero diffs in `style={…}` props and zero diffs in app-root
wrap-chain composition.

### Stage 6 — Memoize tree rewrite (walks 10, 11)

Most subtle stage — sequence carefully:

- **6a** — arena memoize pass alongside legacy. New
  `crates/reflex_codegen/src/memoize.rs::memoize_arena(&mut snapshot)`
  inserts `NodeKind::MemoizeWrapper` nodes and registers `MemoizeBody`
  entries (dedup by `subtree_hash`, optional `struct_eq` in debug to defeat
  collisions). Under `REFLEX_RUST_MEMOIZE_ARENA=1`. Diff harness asserts
  the `(export_name, body_subtree_hash)` set matches what
  `reflex/compiler/rust_memo.py::walk_and_memoize` produces.
- **6b** — Rust emits memo bodies directly from `snapshot.memo_bodies`.
  `rust_memo.emit_memo_modules` becomes a thin shim under the flag.
- **6c** — `crates/reflex_codegen/src/memoize.rs::rewrite_event_triggers`
  walks arena, wraps each `event_callbacks` entry on nodes flagged as
  in-memo-body in `useCallback(…, [deps])` using `vars_used` for deps.
  Pure arena mutation, no PyO3.
- **6d** — `compile_pages` stops calling Python `walk_and_memoize` when
  the flag is set.

**Gate:** byte-identical memo body files (`utils/components/*.jsx`) and
per-page memo wrapper insertions across corpus. Memoize phase <0.1 ms/page
(was 0.52 ms + tree-rewrite cost).

### Stage 7 — Cleanup (delete legacy)

Triggers when, on the full corpus:
1. 1000 successful compiles with strict diff gate green.
2. `uv run pytest tests/units tests/integration tests/benchmarks` pass
   with all `REFLEX_RUST_*=1`.
3. 100 hot-reload cycles on `docs/app` produce byte-identical outputs vs
   fresh compile.
4. Two-week soak with default-on flags, no community-reported diffs.
5. Full-pipeline benchmark ≥5× speedup vs Python baseline.

Then delete: `reflex/compiler/rust_memo.py`, the `_get_all_*` call sites in
`rust_pipeline.py`, the `_add_style_recursive` call in
`compile_unevaluated_page`, `crates/reflex_ir/src/legacy/` (the tree IR),
`crates/reflex_ir/src/parse.rs`, `visitor.rs`, the parity harness, and
`legacy-tree-ir` cargo feature. Keep `REFLEX_RUST_LEGACY_FALLBACK=1` for
one release as emergency revert.

## Critical files

- `packages/reflex-compiler-rust/crates/reflex_ir/src/lib.rs` and new
  `snapshot/` submodule — schema home.
- `packages/reflex-compiler-rust/crates/reflex_pyread/src/freeze.rs` (new)
  and `pyo3_reader.rs` — freeze pass.
- `packages/reflex-compiler-rust/crates/reflex_codegen/src/{jsx.rs,
  page.rs, hooks.rs, harvest.rs, imports_emit.rs, style.rs, memoize.rs}` —
  Rust walks.
- `packages/reflex-compiler-rust/crates/reflex_semantic/src/lib.rs` —
  rewrite from `IrVisitor` to linear `for node in &snapshot.nodes`.
- `packages/reflex-compiler-rust/crates/reflex_py/src/session.rs` — new
  PyO3 entry `freeze_page` plus `compile_page_from_snapshot`.
- `reflex/compiler/rust_pipeline.py` — feature-flag dispatch per stage.
- `reflex/compiler/compiler.py` — split `compile_unevaluated_page` at
  stage 5.
- `reflex/compiler/session.py` — Python wrappers around new PyO3 entries.
- `scripts/diff_legacy_vs_rust.py` — `--stage=N`, `--per-component-diff`,
  `--corpus`.

Files **not** touched (additive constraint):
`reflex/compiler/plugins/*`, `packages/reflex-base/src/reflex_base/
components/component.py`, `packages/reflex-base/src/reflex_base/components/
memoize_helpers.py`, `packages/reflex-base/src/reflex_base/style.py`.
Freeze *calls* the methods on these but does not modify them.

## Risk register

1. **`format_as_emotion` divergence (stage 4)** — handles nested dicts,
   pseudo-selectors, media queries, Vars-in-values. Largest correctness
   surface. *Signal:* byte diff on `style={…}` props. *Fallback:* keep
   `_get_style()` Python call at freeze (one PyO3 per node, ~5 µs) — render
   stays Rust, defer emotion port.
2. **Memoize export-name stability (stage 6)** — today
   `create_passthrough_component_memo` derives names from
   `_get_component_hash` and React `key=` values must match. *Signal:*
   `(export_name, body_hash)` set delta in stage 6a. *Fallback:* keep
   Python passthrough wrapper for name generation; Rust only *decides*
   which subtrees to wrap.
3. **Style merge order (stage 5)** — interacts with theme baseline
   classes, `evaluate_style_namespaces`, MRO. *Signal:*
   `REFLEX_DEBUG_FREEZE` per-node merged-dict diff. *Fallback:* keep
   Python `_add_style_recursive` running before freeze for one extra
   release; freeze captures post-merge style.
4. **Plugin pre_compile reading live Components (stage 5+)** — Tailwind
   etc. scan `component.children` recursively. *Signal:* docs/app
   Tailwind compile under flag. *Fallback:* freeze runs *after*
   `pre_compile`, not before. Python tree stays alive at that point
   anyway.
5. **VarData propagation through Vars-in-props (stage 4)** — every Var
   carries hooks/imports/components in `_get_all_var_data`. Missing one
   means missing imports downstream. *Signal:* missing
   `useContext(StateContexts.X)` lines or import sections in emitted
   JSX. *Fallback:* during transition, union Rust-harvested + Python-
   harvested imports; log deltas.

## Verification

End-to-end gate per stage:
1. `cargo test -p reflex_ir -p reflex_pyread -p reflex_codegen -p
   reflex_semantic` green.
2. `uv run python scripts/diff_legacy_vs_rust.py --stage=N --gate strict
   --corpus docs/app,examples/rust_compiler_demo,examples/counter,
   examples/dashboard,examples/clock` produces zero byte diffs in
   stage-owned files.
3. `uv run python scripts/benchmark_stages.py synthetic:20 3` confirms
   per-stage perf target met.
4. `uv run pytest tests/units tests/integration` pass with
   `REFLEX_RUST_<flag>=1`.
5. Smoke: `REFLEX_RUST_<flag>=1 uv run reflex run-rust` on docs/app,
   visual check in browser that pages render and event handlers fire.

Open before starting Stage 0:
- Measure actual `size_of::<NodeSnapshot>()` with the inventory's `[T; 4]`
  / `[T; 2]` SmallVec sizes against three reference pages (counter,
  dashboard, chatapp). Tune `[T; N]` per field if heap-spill rate >5%
  or struct exceeds 256 bytes.
- Confirm `_native.CompilerSession` PyO3 module name and existing public
  surface in `crates/reflex_py/src/session.rs` so `freeze_page` /
  `compile_page_from_snapshot` slot in without breaking
  `reflex/compiler/session.py` callers.
