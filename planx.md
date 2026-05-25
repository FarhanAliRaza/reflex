# Full optimization of the Rust page+memo compile pipeline

## Context

Profiling `reflex run-rust` on a 4-page snakker app shows the per-iter
budget is **~26 ms**. cProfile attribution and py-spy native frames
(documented in `PROFILING_FINDINGS.md` + the run-rust profiling session
on 2026-05-25) identify eight concrete offenders, all variations of one
theme: the same Python `Component` tree is walked five-to-seven times
per page (memoize, app-wraps, custom code, hooks, pre-memo imports,
post-memo imports, IR pack) and a real Python `Component` is allocated
for every memoize wrapper before its JSX is emitted. Pure-Rust JSX
emit, by contrast, costs **0.14%** of compile time.

The pivot already exists in code but is unwired: `reflex_pyread::freeze_component`
produces a flat `Snapshot` arena that captures every per-node datum the
downstream passes need; `memoize_arena_pass` does the wrapper
substitution as an in-arena O(N) bit-test loop with `subtree_hash`-keyed
dedupe; `emit_jsx_from_snapshot` + `emit_memo_body_jsx` render JSX
without any PyO3 callbacks. The harvest-side modules (`harvest.rs`,
`imports_emit.rs`, `hooks_emit.rs`) read the same arena.

What's missing is (a) a freeze pass complete enough to pass the
`_should_memoize` parity oracle, (b) a `CompilerSession` PyO3 entry that
drives `freeze → memoize → emit` end-to-end and returns page JS + memo
bodies + imports, (c) the production swap in `rust_pipeline.py` from
"Python walk_and_memoize + msgpack tree IR + legacy emit" to that
entry, and (d) deletion of the now-dead Python+Rust legacy pipeline.

Goal: **26 ms → ≤10 ms / 4-page iter**. Achieved by collapsing the
seven Python walks into one PyO3 freeze pass, replacing the
`Component.create` wrapper allocation chain with an in-arena
transform, and skipping no-op file writes. A Salsa-style per-page
emit cache is a planned future addition on top of this work; **not
in scope here.**

---

## Target performance budget (snakker, 4 pages)

| Slice | Today (ms/iter) | After (ms/iter) | Δ |
|---|---:|---:|---:|
| Python `walk_and_memoize` recursion (excl. wrapper alloc) | 1.1 | 0 | −1.1 |
| Python wrapper alloc (`Component.create` + `_post_init`) | 11.0 | 0 | −11.0 |
| Python `_compute_memo_tag` hash chain | 10.0 | 0 | −10.0 |
| Python `_get_all_imports` ×3 + `_get_all_app_wrap_components` + `_get_all_custom_code` + `_get_all_hooks` | ~10 | 0 | −10 |
| Per-memo-body `_get_all_hooks` + `_get_all_imports` | 5.9 | 0 | −5.9 |
| `page_to_ir` msgpack pack | 5.9 | 0 | −5.9 |
| `_value_to_ir` + `LiteralVar.create` normalization | 7.0 | 0 | −7.0 |
| `parse_page` legacy tree-IR parse (Rust) | 1.2 | 0 | −1.2 |
| `should_memoize` PyO3 calls (1820 × 9.5 µs) | 0.9 | 0 | −0.9 |
| **NEW** `freeze_component` (single PyO3 walk) | 0 | 9–11 | +10 |
| **NEW** `memoize_arena_pass` (pure Rust, single arena scan) | 0 | 0.05 | +0.05 |
| **NEW** `emit_jsx_from_snapshot` + `emit_memo_body_jsx` ×N | 0 | 0.10 | +0.10 |
| **NEW** Var-data dedup table (built during freeze) | 0 | 0.30 | +0.30 |
| File I/O (with skip-if-unchanged) | 0.4 | ≤0.1 | −0.3 |
| **Per-iter total** | **~52** (with profiler) / ~26 (raw) | **~10** | **−16 ms ≈ −62%** |

The +10 ms freeze cost is the irreducible PyO3 attribute-read cost for
60-some nodes. Every downstream pass after freeze runs in pure Rust
with the GIL released.

---

## Architectural shape after this work

```
Python rust_pipeline.compile_pages(app, ...)
  └─ for each route:
       compile_unevaluated_page(route)        # user code; unchanged
       sess.compile_page_from_component_arena(   # single PyO3 entry, NEW
         component, route, ...)
         │
         ├─ Rust+PyO3: freeze_component       # one walk, reads every needed attr
         │            (PyO3 → Rust Snapshot)
         │
         └─ py.allow_threads (GIL released):
             ├─ memoize_arena_pass            # pure Rust O(N) flag-test loop
             ├─ emit_jsx_from_snapshot        # page JSX
             ├─ for each memo body:
             │    emit_memo_body_jsx          # body JSX
             ├─ harvest::collect_imports      # pure-Rust arena scan
             └─ return (page_js, memo_files, imports)

       sess.write_if_changed(page_path, page_js)
       for body_path, body_js in memo_files:
           sess.write_if_changed(body_path, body_js)
       sess.union_into(all_imports, page_imports)   # pure Rust
```

Three PyO3 crossings per page (down from eight). No `Component.create`
between page-eval and file write. No msgpack shuttle. No
double-walking for pre-memo vs post-memo imports.

Static artifacts (`context.js`, `theme.js`, `root.jsx`, `_document.js`,
`root.css`, `components.jsx`, `stateful_pages.json`) continue running
through their existing Python-prep → Rust-emit-and-write paths in
`_emit_static_artifacts`. **Scope-limited to page+memo by user
direction.** Skip-if-unchanged applies to them via the same helper.

---

## Critical files

### To modify

| File | Change |
|---|---|
| `packages/reflex-compiler-rust/crates/reflex_pyread/src/freeze.rs` | Capture `_memoization_mode.disposition` → `MemoizationDisposition`; `_memoization_mode.recursive` → `IS_SNAPSHOT_BOUNDARY`; `isinstance(comp, Foreach)` → `IS_STRUCTURAL_MEMO_CHILD`; per-prop-Var reactivity → `HAS_STATE_OR_HOOKS`; Bare-contents reactivity. Cache `(disposition, recursive)` on `PyRefs` by type pointer. Build Var-data dedup table inline during the prop walk. |
| `packages/reflex-compiler-rust/crates/reflex_codegen/src/memoize_arena.rs` | Replace `should_memoize_arena` with full Python parity logic (see "Parity gaps" below). |
| `packages/reflex-compiler-rust/crates/reflex_codegen/src/memoize_pass.rs` | Fuse `collect_memo_candidates` + `insert_memo_wrappers` + `rewrite_memo_event_triggers` into a single arena scan. Preallocate `bodies`/`dedup`/`wrap_redirects` from `nodes.len() >> 3`. Stack-buffer hex in `derive_memo_name`. |
| `packages/reflex-compiler-rust/crates/reflex_py/src/session.rs` | Add `compile_page_from_component_arena(component, route, ...) -> (String, Vec<MemoBodyOut>, PageImports)`. Add `write_if_changed(path, content) -> bool` PyO3 method. Add `union_into(target, source)` pure-Rust merge over an existing dict. |
| `reflex/compiler/rust_pipeline.py` | Replace lines 184-270 with the single-call shape above. Replace `out_path.write_text(rust_js)` at line 269, `_write` at 313, and any other unconditional `write_text` sites with `sess.write_if_changed`. |
| `packages/reflex-compiler-rust/crates/reflex_py/src/session.rs` (writer methods) | `compile_memo_index`, `compile_styles_root`, `compile_theme_module`, `compile_app_root_module`, `compile_document_root_module`, `compile_context_module`, `compile_stateful_pages_marker` — internally hash the buffered output and skip the BufWriter write when the file matches. |

### To delete (Phase F)

| File / function | Reason |
|---|---|
| `reflex/compiler/rust_memo.py` (entire module) | `walk_and_memoize` / `_wrap_with_memo` / `emit_memo_modules` replaced by `memoize_arena_pass` + body emit inside `compile_page_from_component_arena`. |
| `reflex/compiler/ir/bridge.py` (`page_to_ir`, `component_to_ir`, `_value_to_ir`, `_var_data_to_ir`) | Msgpack tree-IR retired; arena Snapshot is the only IR. |
| `reflex/compiler/ir/schema.py`, `pack.py`, `canonical.py` | Schema + pack helpers for the msgpack IR. |
| `packages/reflex-compiler-rust/crates/reflex_pyread/src/imports.rs` | Tree-walking `_get_imports` callback path. Per-node imports captured by freeze; page-level merge by `harvest::collect_imports`. Keep only `apply_alias_prefix` as a utility. |
| `compile_page_from_bytes`, `compile_memo_from_bytes` in `session.rs` | Bridge from msgpack tree-IR → legacy emit. Nothing calls them after the cutover. |
| `reflex_ir::parse_page`, legacy `emit_page` / `emit_page_with_extras` paths | The legacy tree-IR producer + emitter are dead after Phase F. |
| `msgpack` Python dep (`pyproject.toml`) | Sole consumer was `bridge.py`. |

Net delta: **+~600 Rust, −~1500 Python+Rust**.

---

## Parity gaps to close in freeze before the cutover

`reflex/compiler/plugins/memoize.py:120` (`_should_memoize`) reads the
following inputs. Each row maps to a freeze-side capture:

| Input read by `_should_memoize` | Freeze responsibility |
|---|---|
| `component._memoization_mode.disposition` | New: read once per class, cache on `PyRefs`; set 2-bit `MemoizationDisposition` in `NodeFlags`. |
| `isinstance(component, Bare)` | Already set: `IS_BARE` bit. |
| `component.contents._get_all_var_data().{state, hooks, components}` (Bare branch) | New: when freeze sees a Bare, run the prop-Var reactivity check on `contents`. |
| `component.tag is None` and not Cond/Match/structural-memo-child | Already set: `TAG_IS_NONE` bit + `NodeKind` discrimination. Adding `IS_STRUCTURAL_MEMO_CHILD` for Foreach. |
| `_memoization_mode.disposition == ALWAYS` | Same capture as `Never` — 2-bit field handles all three. |
| `component._get_vars(include_children=False)` → per-Var `_get_all_var_data().{state, hooks, components}` | New: during the existing `read_rendered_props` loop, call `_get_all_var_data()` once per Var the loop already touches; OR each `Component` with reactive Vars → set `HAS_STATE_OR_HOOKS`. Per-Var cost ~1 µs since `_get_all_var_data` is cached per Var. |
| `get_memoization_strategy(comp)` = SNAPSHOT and not `is_snapshot_boundary(comp)` | Derived from `IS_STRUCTURAL_MEMO_CHILD` + `IS_SNAPSHOT_BOUNDARY` bits. |
| `is_snapshot_boundary(comp)` and `_subtree_has_reactive_data(comp)` | Snapshot's `PROPAGATES_HOOKS` already bubbles up; reactive-data check is the same per-Var work as above, captured during freeze. |

The corrected `should_memoize_arena` predicate is then 8 bit-tests + 1
enum match per node, ~15 ns. The complete rewritten body is specified
in `MEMOIZE_RUST_PORT_PLAN.md` §C.

---

## The pull-request sequence

Each row is one PR. Tests gate each step; the parity oracle in PR3
guards the cutover in PR5.

### PR0 — Skip-if-unchanged writes (independent, ships first)

- Add `CompilerSession::write_if_changed(path, content)` (PyO3) — fstat + open-for-read + memcmp; on match, return `false` without touching the file.
- Apply at the four current direct `.write_text` sites in `rust_pipeline.py` (line 269 page, line 313 custom component, plus the static-stylesheet path).
- Inside the seven `compile_*_module` Rust writers in `session.rs`, buffer the output, compare against the existing file before flushing.
- Touches: `~50 LOC Rust, ~20 LOC Python`.
- Wall-clock impact: <0.5 ms / iter on compile, but **eliminates Vite HMR cascades** on no-op recompiles — the bigger UX win.
- **Lands now.** Independent of every subsequent PR.

### PR1 — Freeze enrichment: `MemoizationMode` + `IS_SNAPSHOT_BOUNDARY` + `IS_STRUCTURAL_MEMO_CHILD`

- In `freeze.rs::freeze_into_slot`, after `class_name` is read, also read `_memoization_mode.disposition` (cached lookup) and `_memoization_mode.recursive`.
- Set `MemoizationDisposition::{Auto, Never, Always}` and the `IS_SNAPSHOT_BOUNDARY` bit.
- Set `IS_STRUCTURAL_MEMO_CHILD` when class is `Foreach` (kind is already known).
- Cache `(disposition, recursive)` keyed by Python type pointer on `PyRefs` so subsequent same-class nodes do a HashMap hit, not three `getattr`s.
- Unit tests for each disposition; assert `Upload` (or any `MemoizationLeaf`) gets `IS_SNAPSHOT_BOUNDARY`.
- **~80 LOC, +20 µs/page net.**

### PR2 — Freeze enrichment: reactive prop-Var + Bare-contents detection

- Inside the existing `read_rendered_props` loop, for each `Var` value read, call `var._get_all_var_data()` once and inspect `.state` / `.hooks` / `.components`. If any non-empty, set `HAS_STATE_OR_HOOKS` on the node.
- For `class_name == "Bare"`, do the same check on `component.contents` since `read_rendered_props` doesn't run for Bare.
- For `var_data.components` (embedded Components in a Var), don't recurse — those components are already visited by the page tree walk; rely on `PROPAGATES_HOOKS` rolling up from descendants. Track them in a `HashSet<*const PyAny>` so the close pass can flip the bit on the embedding node if no descendant has done so.
- 6 fixtures (state prop, hooks prop, Bare wrapping state Var, Bare wrapping hooks Var, Component-in-prop-Var, no-reactive-data control).
- **~150 LOC, +10 µs/page from cached `_get_all_var_data` calls.**

### PR3 — Corrected `should_memoize_arena` + parity oracle CI guard

- Rewrite `memoize_arena.rs::should_memoize_arena` to the 8-bit-test parity form (see `MEMOIZE_RUST_PORT_PLAN.md` §C).
- Build a parity oracle: a `tests/integration/test_should_memoize_parity.py` that loads the snakker app + the docs app, walks every page, runs Python `_should_memoize(node)` AND `sess.should_memoize_arena(snapshot, idx)` on every node, fails on any mismatch. Run via `pytest tests/integration/test_should_memoize_parity.py` in CI on every PR after this one.
- Per-node cost rises from 15 ns to ~20 ns; on 60-node pages this is ~1 µs total.
- **~40 LOC + ~150 LOC test harness.**

### PR4 — `compile_page_from_component_arena` PyO3 entry (feature-flagged)

- New `CompilerSession` method that takes the evaluated Component + route, runs `freeze_component`, releases the GIL, runs `memoize_arena_pass`, calls `emit_jsx_from_snapshot` for the page and `emit_memo_body_jsx` for each `snapshot.memo_bodies[i]`, runs `harvest::collect_imports` for the page-level imports merge, and returns `(page_js: String, memo_bodies: Vec<{name, js}>, imports: HashMap<String, Vec<PyObject>>)`.
- Add `sess.union_into(target_dict, source_imports)` — pure Rust merge into a caller-owned `dict[str, list[ImportVar]]`.
- Wire `rust_pipeline.py` to call the new method when `os.environ.get("REFLEX_RUST_ARENA_PAGES") == "1"`; legacy path still runs by default.
- Diff harness (`scripts/diff_legacy_vs_rust.py`) must produce byte-identical page+memo output on docs app + snakker before merge.
- **~200 LOC Rust, ~50 LOC Python, no deletion yet.**

### PR5 — Default-on cutover

- Flip `REFLEX_RUST_ARENA_PAGES` default to on. Keep the legacy code path reachable via `=0` for one release in case of regression report.
- Run the parity oracle + diff harness in CI on every commit. Run end-to-end on docs app weekly.
- **~5 LOC.** Watch for one week.

### PR6 — Bulk deletion of dead code

- Delete files listed under "To delete (Phase F)" above.
- Re-run `scripts/diff_legacy_vs_rust.py`; output must still be byte-identical.
- **~−1500 LOC net.**

### PR7 — Var-data dedup table built during freeze

- The existing freeze already walks every Var that appears in a node's props. Insert each unique `_get_all_var_data()` result into `Snapshot.var_data` (already a field) and replace per-node `vars_used: SmallVec<[VarDataRef; 4]>` with the dedup index instead of a fresh copy.
- Dedup key: `id(var)` (the same as the existing freeze HashSet).
- This eliminates the repeated `_get_all_var_data` calls that downstream harvest passes (`collect_imports`, `collect_custom_code`) would otherwise re-invoke; once the data is in `Snapshot.var_data`, every subsequent reader pulls from there in pure Rust.
- Per `PROFILING_FINDINGS.md` §7: `read_var_data_ns / var` is **15,415 ns** — the largest single per-Var cost. With dedup, second-and-subsequent reads are 10 ns (HashMap probe).
- **~120 LOC, saves ~1.4 ms/page** on apps with shared state Vars across nodes.

### PR8 — Micro-optimization sweep inside the arena passes

The list from `MEMOIZE_RUST_PORT_PLAN.md` §5, applied as one PR once
the pipeline is stable:

- Fuse `collect_memo_candidates` + `insert_memo_wrappers` + `rewrite_memo_event_triggers` into a single `nodes.iter()` pass. Saves 30 KB of redundant cache reads ≈ 10 µs/page.
- `Vec::with_capacity(nodes.len() >> 3)` for `memo_bodies` + matching `HashMap::with_capacity` for `memo_dedup`.
- Stack-allocate the hex string in `derive_memo_name` via `write!` into a pre-sized `String` rather than `format!`.
- Reserve `event_callback_overrides` HashMap upfront from a running trigger count.
- `#[inline]` on `should_memoize_arena`.
- Drop `node_pyids` build when not needed (gate behind a flag — current usage is debug-only).
- Estimated total saving: ~20 µs/page.
- **~50 LOC, opportunistic.**

---

## Critical reuse — existing utilities the plan calls

| Need | Reuse this | Path |
|---|---|---|
| Per-node imports/custom-code/hooks capture | `read_imports_summary`, `read_custom_code`, `read_hooks_dict`, `read_hooks_user` | `packages/reflex-compiler-rust/crates/reflex_pyread/src/freeze.rs` |
| Per-class type-pointer cache | `PyRefs` | `packages/reflex-compiler-rust/crates/reflex_pyread/src/pyo3_reader.rs` |
| Subtree hash | `subtree_hash` field, populated by `SnapshotBuilder::finish` | `packages/reflex-compiler-rust/crates/reflex_ir/src/snapshot/builder.rs` |
| Memoize decision predicate | `should_memoize_arena` (to be corrected in PR3) | `packages/reflex-compiler-rust/crates/reflex_codegen/src/memoize_arena.rs` |
| Wrapper-insertion arena pass | `memoize_arena_pass` (to be fused in PR8) | `packages/reflex-compiler-rust/crates/reflex_codegen/src/memoize_pass.rs` |
| Page-level JSX emit | `emit_jsx_from_snapshot` | `packages/reflex-compiler-rust/crates/reflex_codegen/src/page_from_snapshot.rs` |
| Memo body JSX emit | `emit_memo_body_jsx` | same |
| Page-level import merge over arena | `harvest::collect_imports` | `packages/reflex-compiler-rust/crates/reflex_codegen/src/harvest.rs` |
| Import alias prefix transform | `apply_alias_prefix` | `packages/reflex-compiler-rust/crates/reflex_pyread/src/imports.rs` (preserve when deleting the rest) |
| Imports block render | `emit_imports_block` | `packages/reflex-compiler-rust/crates/reflex_codegen/src/imports_emit.rs` |
| Hooks render | `render_hooks` | `packages/reflex-compiler-rust/crates/reflex_codegen/src/hooks_emit.rs` |
| Var-data dedup storage | `Snapshot.var_data` + `VarDataRef` | `packages/reflex-compiler-rust/crates/reflex_ir/src/snapshot/{mod.rs,tables.rs,node.rs}` |
| Skip-if-unchanged write template | `write_web_file` in `reflex/compiler/utils.py:874` | the only existing skip-on-equal pattern in the codebase, lift to a `CompilerSession` method |

---

## Verification

End-to-end harness after each PR:

1. **Unit tests** (per PR, fast)
   - `cargo test -p reflex_codegen -p reflex_pyread -p reflex_ir` — all existing tests must pass + the new fixtures for PRs 1–3.
   - `uv run pytest tests/units/compiler/` — Python-side tests covering `rust_pipeline.py`.

2. **Parity oracle** (PR3 onwards, gates every subsequent PR)
   ```
   uv run pytest tests/integration/test_should_memoize_parity.py -v
   ```
   Loads snakker + docs app, walks every node, asserts Python `_should_memoize` and Rust `should_memoize_arena` agree.

3. **Byte-identical emit diff** (PR4 onwards, gates PR5/PR6)
   ```
   REFLEX_RUST_NO_LEGACY_REBUILD=1 uv run python scripts/diff_legacy_vs_rust.py docs
   REFLEX_RUST_NO_LEGACY_REBUILD=1 uv run python scripts/diff_legacy_vs_rust.py /tmp/snakker
   ```
   Output must show zero diffs in `.web/app/routes/` and `.web/utils/components/`.

4. **Performance regression test** (PR4 onwards, new file)
   ```
   uv run pytest tests/benchmarks/test_pipeline_budget.py -m bench
   ```
   Asserts: per-iter snakker compile ≤ 12 ms (post-PR5), per-iter docs-app compile ≤ 200 ms.

5. **Wall-clock validation** (after PR5, document in PROFILING_FINDINGS.md §13)
   ```
   cd /tmp/snakker
   PROFILE_OUT=/tmp/runrust_snakker_after.prof uv run python profile_runrust.py 20 2
   /home/farhan/code/reflex/.claude/worktrees/rust-bridge-pipeline/.venv/bin/py-spy record --native -o /tmp/flame_after.svg --format flamegraph --rate 250 -- /home/farhan/code/reflex/.claude/worktrees/rust-bridge-pipeline/.venv/bin/python3 profile_runrust.py 200 2
   ```
   Median iter time ≤ 12 ms; pure-Rust slice ≥ 95% of compile time.

6. **Full integration suite** (after PR5)
   ```
   uv run pytest tests/integration -k "not slow"
   ```
   Every existing Playwright + AppHarness test still passes against the cutover pipeline.

---

## Out of scope (deferred to a separate effort)

These are documented here so the deletion in PR6 doesn't accidentally
remove machinery these will need later:

- **Salsa-style per-page emit cache** — hash the page subtree on freeze, key `(page_hash, ir_schema_version) → emitted_js` in a `CompilerSession`-owned cache. Cuts steady-state recompile from ~10 ms to ~0.5 ms for unchanged pages. Will land as a follow-on PR using the same `subtree_hash` already computed during freeze.
- **Static-artifact pipeline** (context.js, theme.js, root.jsx, _document.js, root.css, components.jsx, stateful_pages.json) — out of scope per direction. Continues to run through current Python-prep → Rust-emit paths; benefits from PR0's skip-if-unchanged.
- **Parallel page emit** — defer; prove single-thread budget first.
- **`bun install` skip when imports unchanged** — separate concern; depends on a stable `imports_hash` computed from the arena's import side tables.
- **Custom-component `@rx.memo` Rust port** — `_compile_memo_components` (legacy compiler chain) still runs for user-defined `@rx.memo`. The IR transform handles auto-memoization; user `@rx.memo` is a separate code path.
- **Plugin `pre_compile` Rust port** — Tailwind/Sitemap/Embed plugins walk page ASTs for their own analyses; out of scope.
- **`compile_state` / `compile_client_storage` Rust port** — depends on a Rust-side mirror of Pydantic state introspection; not feasible without a substantial framework-level change.
