# Arena-born components: construct into Rust, keep only user code in Python

Status: **proven feasible** (P0 evidence below) — design fixed, phases P1-P6 not started.
Predecessor: `rust_port_plan.md` (freeze pipeline, complete), two-wave plan
(`~/.claude/plans/vivid-juggling-moonbeam.md`, superseded by this — that plan kept Python
construction and probed it; this one removes Python construction).

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

## 3. The design (fixed by the evidence)

**The handle.** An arena-born component is a *real instance of its own class* with exactly
three Python-side things: `_arena_idx`, a real `children` list of child handles, and a
normal instance `__dict__`. Everything else — props, style, event values, custom_attrs,
special_props, tag/alias/library overrides — lives in the Rust staging arena.
`__getattr__` materializes from the arena on read (0.10 µs, override classes only);
`__setattr__`/proxy containers write through. Because it IS its class: `isinstance`,
method dispatch, instance-level method reassignment, and `id()`-stable dedup all work
unmodified. Children stay a Python list because tree-rewriting passes mutate it and
identity walks traverse it; a list per node is noise next to 46 µs of prop machinery.

**The push.** `Component.create` → (children construct first, depth-first, as today) →
ONE PyO3 call `push_node(class_id, child_idxs, raw_kwargs)`. Rust classifies each kwarg
against the per-class schema (prop / event trigger / style key / custom attr, rename map
applied), converts values (scalars, interned strings, container→JS literal, native
RustVar→struct ref, event values→kept Py handles for the probe phase), validates types,
and stores the node. The per-class schema is built once per class from one Python
introspection (`get_fields` + `get_event_triggers` + `_rename_props`) — the
`ClassMetadata` machinery already does exactly this pattern.

**The seal.** The staging arena keeps child indices as per-node Vecs so post-construction
mutation is cheap. At compile time a pure-Rust seal pass runs the override probes
(per-class-gated, exactly today's skip-list machinery), folds style, assembles event
chains (`assemble_chain_js`), and lays out the contiguous-children `Snapshot` the existing
memoize+emit consume **unchanged**. The freeze survives only as the grafting path for
rich subtrees (memo definitions, app-wraps, legacy-gated classes) — it walks them into
the same arena, as it does today.

**The gate.** A construction-mode flag (context-local), flipped on by the Rust pipeline
around page evaluation only. Off ⇒ rich objects (module import, runtime events, legacy
`reflex run`, tests). Per-class opt-out list for pathological classes (DebounceInput).
Global kill switch `REFLEX_ARENA_CONSTRUCT=0`.

## 4. Phases (every phase ships with: oracle 27/27 byte-identical, corpus, docs app compile+run, unit suite)

- **P1 — Schema.** Extend `ClassMetadata` with the full construction schema (field names
  + types + defaults, trigger names, rename map, style-key classification). Pure addition;
  freeze keeps running. Build it lazily on first construction per class.
  *Risk: low.*
- **P2 — Staging arena + handle.** Real `push_node` (the prototype, productionized:
  schema-driven, proper literal conversion via the existing `reflex_vars` literal code,
  not the bench's stand-in). `Component.__new__` fast path behind the mode flag +
  per-class gate; `__getattr__`/`__setattr__` routing; ProxyDict/ProxyList for
  `custom_attrs`/`style`/`special_props` writes. Freeze learns to consume arena-born
  nodes by index instead of re-reading them (hybrid trees work). The 24 write-through
  sites from the audit are the test matrix.
  *Risk: HIGH — this is the compatibility cliff; land behind default-off flag.*
- **P3 — Style fold at construction.** Port `_add_style_recursive` semantics into the
  seal (per-node `_add_style` probes for override classes, App-style per-class entries,
  instance style last-wins, VarData merge order). Deletes the last Python tree pass in
  the Rust pipeline. The old plan's P1 differential suite applies as-is.
  *Risk: high (byte-visible CSS).*
- **P4 — Events at the seal.** Trigger values stored at construction (already Py
  handles); arg-spec parsing cached per (class, trigger); chains assembled in the seal
  via `assemble_chain_js`. `rx.input`'s 112 µs/node pathology dies here.
  *Risk: medium.*
- **P5 — Freeze bypass.** Pure-arena trees seal directly to `Snapshot`; freeze runs only
  for grafted rich subtrees. The ~7.5 s freeze slice goes to ~0 for arena trees.
  *Risk: medium (the seal must reproduce freeze byte-semantics — the oracle is the gate).*
- **P6 — Default-on + cutover.** Flip the flag default under the Rust pipeline, audit-mark
  remaining opt-out classes, delete dead freeze paths for base classes, strip the bench
  scaffolding.
  *Risk: low.*

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
