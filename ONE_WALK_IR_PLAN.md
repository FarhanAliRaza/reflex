# One-Walk IR Plan

Goal: the user's `def page()` construction walk produces the Rust IR (`Snapshot`)
directly. No separate freeze re-read walk. No fallbacks, no shortcuts. Performance
first. Exactly one PyO3 walk of the Component tree. Iterative, not recursive.

Today: `compile_unevaluated_page` builds the Component tree (walk #1), then
`freeze_component` (reflex_pyread/freeze.rs) re-walks it via ~100 getattr/method
calls per node to build the `Snapshot` (walk #2). We delete walk #2.

## Strategy

As each `Component.create()` runs (bottom-up: children built before parents),
append ONE primitive node-record to a per-page buffer. The record carries every
per-node field the `Snapshot` needs (rendered props, var_data, events, child
record-indices, control-flow payload). Class-level data (tag/imports/hooks/rename
schema) is cached once per class. At end-of-eval, one PyO3 crossing hands the
buffer to Rust, which builds the `Snapshot` iteratively (BFS, no recursion) and
runs the existing memoize + emit tail unchanged.

Key enabler: vars are `RustVar`, so `_js_expr`/`_get_all_var_data` are native —
rendering props + extracting var_data at construction is cheap.

## Record format (per node) — must reproduce `NodeSnapshot`

Primitive tuple, no Component/Var refs (matches test_arena_ir_completeness):
- `kind: int`            NodeKind discriminant
- `tag: str`             "" ⇔ no tag
- `style_key: str`       type(self).__qualname__
- `style: str`           pre-rendered emotion CSS (""=none)
- `rendered_props: [(name, js)]`
- `event_callbacks: [(trigger, js)]`
- `imports: [import_entry]`        class static + var imports
- `hooks_internal/hooks_user: [hook_entry]`
- `custom_code: str`
- `dynamic_imports: [str]`
- `ref_name: str`
- `var_data: [var_data_entry]`     deduped downstream by Rust
- `children: [record_idx]`         indices into the buffer
- `control_flow: payload|None`     cond/foreach/match
- flags derived in Rust from kind/tag

Side tables built by Rust from records: var_data dedup, subtree_hash (close pass),
memoize, wrap_redirects. app_wraps + app_style_map come from page-level records.

## Phases (checklist)

- [ ] P0  Rust `build_snapshot_from_records` (iterative BFS arena build) +
          reuse close_snapshot + emit tail. Parity test with hand-built records
          for a trivial page (JS == freeze path).
- [ ] P1  Construction recorder for plain Element/Text/Fragment/Bare. Route
          rust_pipeline through it. Gate: arena tests + JS parity on simple pages.
- [ ] P2  Control flow (cond/foreach/match) — capture iter var + template +
          loop binding. Gate: test_arena_parity + foreach/match + JS parity.
- [ ] P3  App-style merge + page wrap (Fragment/title/meta) recorded; Rust does
          the 3-layer merge (no Python _add_style_recursive fallback).
- [ ] P4  Cutover: record path is the only path. Delete freeze_component re-read.

## Validation contract

- 47 arena IR tests stay green; single-walk crossing count → 0 freeze crossings.
- JS byte-parity vs freeze path across the synthetic corpus.
- Full tests/units/{compiler,vars,components} — only the 6 pre-existing failures.
- benchmark_stages / profile_full_rust_compile: freeze/pyread slice collapses.

## Status

**P0 DONE + validated.** Recovered the wire-format round-trip infra from `ee2a1719`
(`snapshot_dump.rs`, `from_wire.rs`, `arena_record.py`, round-trip/gather/dump tests),
re-wired it into the post-merge crate:
- `dump_snapshot` now emits the `snapshot_dump` (wire) format; `from_wire` is its inverse.
- Extracted `emit_snapshot_to_js` (shared GIL-released memoize+emit tail); added
  `compile_page_from_arena` (Rust + Python) = `build_snapshot_from_wire` + shared emit.
- Ported HEAD's `test_arena_ir_completeness` to the wire format (kind int→name, `flags`,
  range-into-dense-backing var_data, `(code,position)` hooks).
- 167 arena/wire/gather/dump/parity tests green. Full suite: only the 6 pre-existing
  failures, 3205 pass.

**Proven:** `gather_arena(c)` → `compile_page_from_arena` is **byte-identical JS to the
freeze path** on the real `_complicated_page` + `_stateful_page` fixtures (memo bodies
included). The gatherer already handles vars, events, control flow (cond/foreach/match),
styles, nesting — so the per-node extraction the one-walk recorder needs exists.

### P1 progress — gatherer coverage (toward no-fallback)
- FIXED: gatherer **string double-escaping** bug — Bare→Text now decodes the JS string
  literal (`_decode_js_string_literal` via `json.loads`, matching freeze's
  `decode_js_string_literal`) instead of `expr[1:-1]`. Validated parity on newline/quote/tab
  content.
- CLOSED: **custom_code** + **dynamic_imports** gaps (gather them per-component, mirroring
  freeze's `read_custom_code`/`read_dynamic_imports`). Validated **full byte-parity** on
  `rx.markdown` (simple + rich), `rx.icon` (lucide/dynamic imports), and the `_complicated_page`
  fixture. markdown moved into the supported parity corpus; 170 gather/arena tests green;
  full compiler suite only the 3 pre-existing failures.
- REMAINING gather gap: **components-in-props** (`_get_components_in_props`) — still raises
  (guard pinned by `test_gather_rejects_components_in_props`). Needs recursive component-var
  rendering for full no-fallback coverage.
- `gather_arena` is still **recursive** (`_fill`); needs iterative conversion.

### P2 progress — the one-walk recorder + re-layout (the headline)
DONE + test-pinned: `_OneWalkRecorder` + `gather_arena_one_walk` in `arena_record.py`.
- Records each node's gathered data in construction (post) order, then `finalize`
  re-lays-out to the **exact freeze arena order** (mirrors `_fill`/`_fill_match`, incl. the
  Match contiguous-body layout the `subtree_hash` close pass depends on), operating only
  on records — no second Python-tree walk.
- var_data registered in record order (differs from freeze) but `vars_used` stays
  consistent → emitted JS identical (validated).
- Fixed a real bug: `_record_postorder` must NOT descend into Foreach/Match `.children`
  (the unrendered template, whose loop var pollutes the gather); bodies are materialized
  inside `record()`.
- `test_gather_one_walk_emit_matches_freeze` over the full supported corpus (plain,
  reactive, events, cond, foreach×2, match, markdown, …) green; 118 gather tests pass;
  full suite only the 6 pre-existing failures.

### Remaining
- ~~**Nested foreach in `_stateful_page`**~~: **FIXED.** Root cause was *not* a key/order
  edge — it was an `id()`-recycling bug. The recorder keys records by `id(component)`;
  a Foreach body is materialized by `render_component()` and dropped once `record()`
  returns, so CPython recycled its `id()` into the *next* Foreach's body, and the
  id-keyed dedup grafted the simple Foreach's `rx.text(elem)` node onto the nested
  Foreach in place of its real `rx.text(f"{i}")` child. Fix: the recorder keeps
  materialized bodies alive (`self._materialized`) for the whole walk so their ids
  can't be recycled. Pinned by `test_one_walk_recovers_transient_foreach_body` +
  `test_corpus_one_walk_emit_matches_freeze_when_supported`. `_stateful_page` and
  `_complicated_page` now emit byte-identical JS through the one-walk recorder.
- **create() hook (true 1 walk)**: replace `_record_postorder` (a stand-in second walk)
  with recording inside `Component.create()` via a reflex_base hook slot, so the IR is
  produced *during* the user's construction walk. (`arena_record` is reflex.compiler →
  needs a layering callback registered into reflex_base.Component.)
- components-in-props (still raises); P3 app-style/page-wrap; P4 cutover + delete freeze.

Core mechanism proven + pinned. Remaining: nested-foreach edge, create() hook, cutover.

---

## PIVOT (2026-06-02): one-walk-via-Python-gather abandoned — it was perf-negative

Benchmarked the gather/record path vs the Rust freeze re-read it would replace:
**Python gather is ~30% SLOWER than freeze** (see `project_onewalk_perf_negative` memory).
freeze isn't "pure Rust" — it's a thin Rust orchestration that calls *back into Python*
per node (`_get_imports`, `_get_vars`, `_get_style`). Those callbacks are the cost, and
doing them in Python (gather) is slower than doing them via freeze's optimized PyO3.

**Decision (user-directed):** keep freeze as the single data-getting path; delete the
Python gather; make freeze's per-node Python callbacks cheaper by doing the work in Rust.

### Done
- **Deleted the Python gather + wire round-trip apparatus**: `reflex/compiler/arena_record.py`,
  `test_arena_gather.py`, `test_arena_ir_completeness.py`, `test_snapshot_dump.py`,
  `test_arena_wire_roundtrip.py`, the `dump_snapshot` / `compile_page_from_arena` session
  wrappers (Python + Rust pymethods), and `from_wire.rs` / `snapshot_dump.rs`. **One path.**
- **#1 Style → Rust**: `read_style` now fast-paths the base `Component._get_style` — reads
  `self.style` and renders the emotion object literal in Rust (`render_style_object`), instead
  of `_get_style()` rebuilding the CSS `Var` (a `LiteralVar` per property) every node. Classes
  that override `_get_style` (recharts) keep the generic path. Byte-identical across the corpus,
  both benchmark pages, and 8 style edge cases (reactive/pseudo/breakpoints/nested/recharts).
  Win: style-heavy page data-getting **13.3 ms → 11.9 ms (−10%)**; flat on style-light pages.

### #2/#3 imports — SAFE widening done; big win needs the reactive-node port
**Done (byte-clean):** widened the existing Rust import fast path
(`default_import_instance_is_trivial` in `freeze.rs`) from "no props/style at all" to
"styled/propped OK as long as no Var carries imports, no events/special_props/deps/ref,
no key/id/class_name". Added `ref_is_present` / `var_has_imports` / `style_var_has_imports`
helpers. Verified byte-identical across 20 corpus+bench pages, 8 style cases, and 27
import cases (events/reactive/icons/markdown/control-flow/recharts/forms; before-vs-after
JSON diff = 0). Full suite green (6 pre-existing failures only).

**But the gain is small (~3%):** `_get_imports` is ~8.6 ms/page (cumulative, incl. its
internal `_get_vars`) of the ~13 ms data-getting on `complicated` — but real pages are
mostly **reactive/event nodes**, which still bail to `_get_imports`. The safe widening only
catches non-reactive styled/propped nodes (a minority). Cumulative wins so far (complicated
data-getting): ~13.3 ms → ~11.7 ms (~12%), almost all from #1 (style).

**The big win requires the reactive-node port (high build-correctness risk):** to skip
`_get_imports` for reactive/event nodes, Rust must reproduce its full aggregation inline
during the per-node reads it already does — library + `Imports.EVENTS` (events) + per-var
`var_data.imports` (collected during `register_var_data`) + `_get_dependencies_imports`
(lib_dependencies) + `_get_hooks_imports` (ref→useRef/refs, lifecycle→useEffect, user/added
hook var_data imports) + `add_imports`, merged via `merge_parsed_imports` — byte-exact. A
miss silently corrupts the page import block / `bun install`. Awaiting go/no-go.

### (superseded note) #2 imports / #3 memoize reactive-check are ONE lever, and it's a real port
`_get_imports()` is instance-cached and its cost is the internal `self._get_vars()` call (the
179k `_get_vars` calls in the profile). A Rust fast path (`read_default_imports_summary_if_safe`)
already bypasses `_get_imports` for *trivial* nodes; its triviality gate is load-bearing — it
guarantees the node contributes only its library import (no event/hook/dependency/var imports).
Widening it requires reimplementing the full import aggregation (library + `Imports.EVENTS` +
`var_imports` + `_get_dependencies_imports` + `_get_hooks_imports` + `add_imports`, merged via
`merge_parsed_imports`) in Rust — these feed `bun install` / `package.json`, so an error breaks
user builds silently. Real sub-project, not a patch. Awaiting go/no-go on the risk.

Byte-parity oracle for any future freeze change: capture `compile_page_from_component_arena`
output (page + memo bodies + imports) for the corpus + benchmark pages BEFORE, compare AFTER.
