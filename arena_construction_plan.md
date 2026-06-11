# Arena-born components: construct into Rust, keep only user code in Python

Status: **proven feasible** (P0 evidence below) — design fixed after a construction-path +
builder-surface exploration (2026-06-11); milestones M1-M5 below are the executable plan.
M1 landed 2026-06-11. Predecessor: `rust_port_plan.md` (freeze pipeline, complete), the
probe-walk two-wave plan (superseded — it kept Python construction and probed it; this
removes Python construction).

## 1. Why: the measured problem

Bucketed profile of full docs-app evaluation (427 pages, 2026-06-10):

| slice | share | nature |
|---|---|---|
| truly user code (docgen, markdown, exec'd demos) | **~16%** | irreducible |
| `reflex_base` Component/Var/Style construction | 36% | framework tax |
| C-builtin churn it causes (5.0M isinstance, 1.65M abc checks, 1.6M getattr, 640k setattr, 147k Var creates) | 30% | framework tax |
| typing/inspect annotation machinery | 9% | framework tax |

The page functions are cheap; each `rx.box(...)` paying a heavyweight Python constructor —
and the freeze then re-reading the object back through PyO3 — is ~80% of evaluation.
Build the node in Rust at construction and **both** costs disappear.

## 2. P0 proof (done, 2026-06-11)

### 2a. Benchmark — `CompilerSession.bench_push_node` (prototype in `reflex_py/src/session.rs`)

One PyO3 call per node: classify kwargs against a cached per-class schema, convert values
to owned Rust data (interned strings, scalars, JS literals for containers, direct struct
reads for native Vars, Py handles for event values), push node. 20k reps each:

| shape | Python `Component.__init__` today | arena push | factor |
|---|---|---|---|
| `rx.text("hi", size="3")` | 20.6 µs | 0.69 µs | 30× |
| `rx.box(style={nested dict})` | 14.8 µs | 0.93 µs | 16× |
| `rx.input(value=<state var>)` | **112.6 µs** | 0.47 µs | 240× |
| `rx.button(on_click=<handler>)` | 36.3 µs | 0.44 µs | 83× |
| empty call (pure crossing floor) | — | 0.24 µs | — |
| proxy read-back of one prop | — | **0.10 µs** | — |

Average 46 µs → 0.63 µs (**73×**). Extrapolated over the ~147k nodes a docs compile
constructs: ~6.8 s of construction → **<0.1 s**. Honest caveats: the bench defers event-chain
building to the probe phase (chain *assembly* is already Rust — `assemble_chain_js`), and
skips enum-style prop validation; the realized factor will be lower but the conclusion
(crossing + classification + conversion is sub-µs and NOT the bottleneck) is proven.
Note `rx.input` at 112 µs: Var-valued props are today's worst case — the biggest single win.

### 2b. Audits (3-agent sweep over reflex/ + packages/, 90 findings)

**Mutation audit — 28 post-construction mutation sites.**
24 are plain attribute/container writes a write-through handle covers:
`create()` overrides patching the returned component (Form's `handle_submit_unique_name`,
RadixThemes `alias`/`library`, SimpleIcon `tag`, Clipboard child `id`, Upload
`special_props`, Foreach/Debounce `children`, banner `children.insert`), compile passes
rewriting `style`/`children` (`_add_style_recursive`, ApplyStylePlugin, memo passthrough
holes, `add_meta`), radix Progress mutating `custom_attrs` inside `add_style`.
4 sites reassign **methods** on instances (DebounceInput binds the child's `_get_style`/
`_rename_props`/`_get_all_custom_code`; MemoizeStatefulPlugin swaps `_get_all_refs`) —
dissolved by the handle design below (real instance `__dict__`), with DebounceInput
additionally legacy-gated for safety.

**Read-back audit — 41 sites; the critical finding.**
The per-node-hot Python readers (`render()`, `_get_vars`, `_get_all_imports/hooks/
custom_code/refs`, memoize plugin walks) are **legacy-compile-path only** — the Rust
pipeline already replaced them with the freeze, which this design also replaces. In the
Rust pipeline, once the style fold moves to construction (P3), there is **no per-node-hot
Python read left**. Override methods (~40 classes) read only their own domain props, at
0.10 µs/read through the proxy. Consequence: **arena construction must be gated to the
Rust pipeline**; the legacy path keeps rich objects untouched.

**Lifecycle audit — 21 sites; forces the second design decision.**
Components outlive compiles in three ways: module-level caches (`MEMOS` definitions,
`GLOBAL_CACHE`, `app.toaster`, app_wrap closures), disk pickling (compile-cache blobs with
app-wrap components; Granian process spawn pickling the app), and `id()`-keyed dedup
(plugin `_owned`, app-wrap `ignore_ids`). Consequence: **only page-evaluation-scoped
construction is arena-born**; anything created at import time, at runtime
(`ComponentState.create` during events, dynamic components), or stored beyond the page
(app-wrap factory outputs) stays a rich Python object. The cache keeps pickling rich
wraps — unchanged.

## 3. The design (fixed by the evidence + construction-path exploration)

Three tensions from the audits got resolved by reading the construction path in detail
(`_create` at component.py:1366, `_post_init` at 1019-1181, `ComponentField.__get__` at
148-175, the builder reserve/fill pattern in snapshot/builder.rs):

**The handle — no `__getattr__` interception at all.** An arena-born component is a *real
instance of its own class*. Its `__dict__` holds: `_arena_idx`, a real `children` list of
child handles, and the **raw kwarg values mirrored in** (plain dict writes — the final
setattr loop is 0.11s of 14.6s; the expensive parts of `_post_init` are LiteralVar
wrapping + `satisfies_type_hint` validation + `EventChain.create` + Style normalization,
and THOSE are what move to Rust). Unset fields resolve through today's class-attr
defaults / `ComponentField` descriptors unchanged — correct because unset means default.
Set fields read back as raw values, which only matters on override classes — and those
stay rich (gated). `isinstance`, method dispatch, instance-level method swaps, and
`id()`-stable dedup all work because it IS its class.

**The push.** `Component._create` branches: when arena mode is active and the class is
eligible, skip `_post_init` entirely — mirror raw kwargs, ONE PyO3 call
`push_node(schema_id, raw_kwargs)`. Rust classifies each kwarg against the per-class
schema (prop / event trigger / style key / special attr, rename map), converts values
(scalars, interned strings, container→JS literal via the real `reflex_vars` literal code,
native RustVar→struct ref + var_data, event values→kept Py handles), structurally
validates, stores a staged node, returns its index. The schema is built once per class
from one Python introspection (`get_props` + per-field `type_origin is Var` +
`get_event_triggers` + `_rename_props`) and registered into `ClassMetadata` — the
existing per-class-cache pattern.

**Write-through is `__setattr__` only.** Normal `object.__setattr__` always; if
`_arena_idx` exists and the name is a schema field, also update the staged node. This
covers all 24 audited post-create mutation sites (RadixThemes `alias`, Form's submit
hash, Upload `special_props`, style write-backs). Children need NO write-through — see
the seal. No ProxyList/ProxyDict machinery.

**The seal walks the Python children lists — staged nodes store no child links.** At
compile time, one walk reads ONLY `__dict__["children"]` + `__dict__["_arena_idx"]` per
handle (~0.3 µs/node): staged payloads are copied into `SnapshotBuilder` slots (the
existing reserve/fill contiguous-range pattern; graft point = `freeze_children_for`,
freeze.rs:677), and handles WITHOUT `_arena_idx` (rich subtrees: gated classes, memo
definitions, app-wraps) are grafted via today's `freeze_into_slot`. Reading children from
Python at seal time makes every list mutation (`append`, `insert`, wholesale replacement
by compile passes) correct by construction — no sync protocol. The seal also runs
override probes (today's skip-list machinery), folds style, builds event chains, and
registers var_data; downstream (`memoize_arena_pass`, emitters, byte-oracle) consumes the
identical `Snapshot` unchanged.

**The gate.** A contextvar holding the active staging session, set by the Rust pipeline
around page evaluation only. Off ⇒ rich objects everywhere (module import, runtime
`ComponentState`, legacy `reflex run`, tests). Per-class eligibility: `_post_init` is
base AND `_render` is base AND not denylisted (DebounceInput's method-swap create);
override-bearing classes (~40, <3% of nodes) stay rich so their probes read real objects.
Env kill switch `REFLEX_ARENA_CONSTRUCT=0`.

**Validation note.** The arena path replaces `satisfies_type_hint` with structural type
checks in Rust. Output bytes are unaffected (validation only raises); the rich path keeps
full validation. Documented behavior difference behind the flag.

## 4. Milestones (each ships green: oracle 27/27 byte-identical, corpus, docs compile+run, unit suites)

- **M1 — Per-class construction schema. DONE (2026-06-11).** Python `ConstructionSchema`
  builder mirroring `_post_init`'s classification (component.py:1031-1148);
  `register_class_schema` PyO3 entry; stored on `ClassMetadata` (pyo3_reader.rs). Inert —
  nothing consumes it yet. Gate shipped: differential sweep of schema vs a literal
  `_post_init` transcription across all loaded Component classes (>200: core/radix/
  lucide/markdown/sonner/code; enterprise covered by the docs-app compile smoke),
  behavioral spot checks driving `create()` per category, Rust round-trip classify
  equality, cargo classify tests
  (`tests/units/reflex_base/components/test_construction_schema.py`,
  `tests/units/compiler/test_construction_schema.py`). Oracle 27/27; docs app 427/427
  compiles. *Risk: low.*
- **M2 — Style fold at the seal, on RICH objects first. DONE (2026-06-11).**
  `compile_unevaluated_page` gained `apply_style: bool = True`; rust_pipeline passes
  False (fold-in-freeze on by default; kill switch `REFLEX_STYLE_FOLD=0`) and hands
  `app.style` to the arena entry. Shape that landed (cheaper than a full Rust port,
  byte-safe by construction): the non-recursive fold extracted to
  `Component._apply_style_fold` (single source with `_add_style_recursive`); the freeze
  replicates only the GATE in Rust (per-class `add_style`-chain + `_add_style`-base via
  `class_bool_flag`, per-class-per-freeze App.style entry probe, per-node style-is-dict)
  and calls the Python helper for folding nodes only (~2% of docs nodes — the ones that
  paid Python anyway); the Python recursion over the other ~98% is gone. Scope exactness:
  fold activates at a `_style_fold_root` instance mark set by `compile_unevaluated_page`
  (the Fragment/meta wrap is never folded), propagates along children edges only — match
  arms/default yes (alias children), foreach bodies NO (freeze re-renders them fresh;
  legacy bytes never saw them folded). Gate shipped: oracle 27/27; 16-fixture
  differential suite (`tests/units/compiler/test_rust_style_fold.py`: add_style chains/
  MRO order, App.style by class + by `cls.create`, instance-style-wins, style-Var kwarg,
  Breakpoints/pseudo, foreach/match/cond, wrapper/meta scoping via Title, VarData
  imports, UserWarning parity, end-to-end kill-switch byte-equality); docs app per-page
  A/B over all 427 pages — **426 byte-identical**, the 427th (data-editor) fails its own
  legacy A/A (random unique hook names; pre-existing, pinned uncacheable). Harness note:
  A/B must compare two deepcopies — memo subtree hashes are sensitive to set-rebuild
  iteration order, so original-vs-copy churns memo names with zero behavioral diff.
- **M3 — Arena construction + seal (the cliff; default-off flag).** Productionize
  `push_node` from the bench prototype; `_create` fast path + raw-kwarg mirroring;
  `__setattr__` write-through; plain-str child fast path (push Bare text node directly,
  skipping `LiteralVar.create` + `_unsafe_create` — text children are the most numerous
  nodes). Seal: children walk + staged copy + rich graft, hybrid in BOTH directions.
  Events at the seal call `EventChain.create` + existing rendering per trigger (same cost
  as today, just moved). Gate: everything byte-identical with flag ON; the 24-site
  mutation matrix as regression tests. *Risk: HIGH — the compatibility cliff.*
- **M4 — Event optimization.** Cache parsed arg-specs per (class, trigger); assemble
  chains via `assemble_chain_js` without per-trigger `LiteralVar.create`. Kills
  `rx.input`'s 112 µs/node pathology end-to-end. *Risk: medium.*
- **M5 — Default-on + measure + cleanup.** Flip the flag default under the Rust pipeline;
  denylist audit; re-profile docs (target ~4s); strip `bench_push_node` scaffolding;
  update this doc + STATUS_TODO with measured numbers. *Risk: low.*

## 4b. Critical files

- `packages/reflex-base/src/reflex_base/components/component.py` — `_create`/`_post_init`
  fast path, `__setattr__`, schema builder (construction semantics source of truth)
- `packages/reflex-compiler-rust/crates/reflex_py/src/session.rs` — `push_node`, staging
  arena, seal entry (the `bench_push_node` prototype is the seed)
- `packages/reflex-compiler-rust/crates/reflex_pyread/src/freeze.rs` — style fold (M2),
  graft branch + seal walk (M3)
- `packages/reflex-compiler-rust/crates/reflex_pyread/src/pyo3_reader.rs` —
  `ClassMetadata` schema storage
- `packages/reflex-compiler-rust/crates/reflex_ir/src/snapshot/{builder,node,tables}.rs` —
  StagedNode→NodeSnapshot copy
- `reflex/compiler/rust_pipeline.py` + `reflex/compiler/compiler.py:907` — mode
  contextvar, `apply_style` kwarg
- `packages/reflex-compiler-rust/crates/reflex_vars/src/py.rs` — literal conversion +
  `assemble_chain_js` reuse

## 4c. Verification (every milestone)

`uv run maturin develop --release` (from packages/reflex-compiler-rust) →
`uv run python scripts/parity_oracle.py check` →
`uv run pytest tests/units/compiler tests/units/vars tests/codegen_corpus tests/units/components -q`
(known-6 failures only) → docs app: in-process compile of all 427 pages byte-diffed
against flag-off output, then `CI=1 uv run reflex run-rust` smoke → per-milestone
differential suites named above → freeze/seal timers re-measured. Known pre-existing
failures (STATUS_TODO): the 6 compiler ones + full-suite DynamicState pollution.

## 5. Projection (docs app, single-threaded, warm cache)

| | today | after P6 |
|---|---|---|
| user code (docgen/markdown/demos) | ~2 s | ~2 s |
| component construction | ~7 s | ~0.2 s |
| freeze re-read | ~7.5 s¹ | ~0 |
| override probes + events | (inside above) | ~0.5 s |
| Rust memoize+emit + writes | <0.5 s | <0.5 s |

¹ uncacheable pages only, on warm runs. End-to-end: **~16 s → ~4 s** without pools or
cache dependence; a normal-sized app's compile becomes near-free. Numbers are projections
from the P0 bench; each phase re-measures.

## 6. Kill criteria

Abandon (keeping P1's schema, which is useful regardless) if P2 shows: proxy reads appear
in a per-node-hot path we missed (>1 read/node average on base classes), or hybrid-tree
freeze grafting can't hold byte parity, or the write-through matrix exceeds the 28 audited
sites by an order of magnitude.
