# Arena-born components: construct into Rust, keep only user code in Python

Status: **COMPLETE (2026-06-11)** — all milestones landed (M1, M2, M3 phases 1+2a, M4,
M5 default-on), each byte-gated (oracle 27/27, fork-pair docs diff 427/427). One design
element — M3's staged-node seal (`push_node` + Rust-side prop storage) — was formally
SUPERSEDED by phase-2a measurement: the mirror fast path captures the construction win
without it, and the staged seal's remaining value (~100-200 ns/prop on the freeze's
13% props slice) no longer justifies its bulk and byte-risk (details in M3 below).
Predecessor: `rust_port_plan.md` (freeze pipeline, complete), the probe-walk two-wave
plan (superseded — it kept Python construction and probed it; this removes Python
construction).

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
  - **Phase 1 DONE (2026-06-11): gate + `_create` mirror fast path, default-off.**
    `arena_construction()` contextvar scope (component.py) set by rust_pipeline around
    page evaluation under `REFLEX_ARENA_CONSTRUCT=1`. Eligible classes (`_post_init` is
    base, stock `Style` factory on the style field; cached per class) skip `_post_init`:
    kwargs mirror into `__dict__` with `LiteralVar` wrapping for Var-typed props (Var
    values pass through unchanged — proven identity at base.py:1414) and all-str
    class_name lists joined; calls carrying event triggers / style inputs / special
    attrs / unknown names fall back per call. Validation (`satisfies_type_hint`,
    children checks) skipped on the fast path — the documented flag-gated difference.
    No `__setattr__`/write-through needed in this phase: the mirror IS the storage, so
    all 24 audited mutation sites work natively. M1's schema got its first consumer
    (per-kwarg classification drives eligibility). Gate shipped: 16-fixture parity
    suite (`tests/units/compiler/test_arena_construct_mirror.py`) + **fork-pair docs
    diff: 427/427 pages byte-identical rich-vs-arena** (fork twice per route from one
    imported parent — children share random/counter/intern state, eliminating ALL
    evaluation nondeterminism incl. upload/data-editor). Measured on docs: 60.9% of
    in-scope constructions skip `_post_init` (50.4k/82.7k; remainder = style-kwarg and
    event-trigger calls — phase 2/M4 territory); only 2.1k compile-time constructions
    occur outside the scope (freeze-time foreach re-renders — candidates for scope
    widening in phase 2), the other ~233k are app-import-time docgen (correctly rich).
  - **Phase 2a DONE (2026-06-11): full-surface mirror (style + special attrs +
    events).** `_arena_mirror_kwargs` now replicates `_post_init` end-to-end minus
    validation: the exact `Style` merge (list-of-dicts, Breakpoints/Var `{"&": ...}`
    wrap, css shorthand keys), data-/aria- kebab-casing into `custom_attrs` (in-place
    update of a caller-supplied dict, like `_post_init`), `EventChain.create` per
    trigger (same call), caller-supplied `event_triggers` dict copy, Var `class_name`
    passthrough. Fallback remains only for unknown `on_*` names (so `_post_init`
    raises), Var-bearing class_name lists, and malformed style shapes. Gate: parity
    suite extended to 18 fixtures incl. error-parity (str style raises both paths);
    fork-pair docs diff 427/427 byte-identical. Measured: **88.0%** of in-scope docs
    constructions skip `_post_init` (72.8k/82.7k; the rest are memo classes with their
    own `_post_init`, by design). Honest per-call factors (full `create()` incl.
    children normalization, not the bare push the P0 bench measured): text 1.9×,
    style-box 1.3×, input 1.3×, button-with-event 1.1×.
  - **Re-derived facts from phase-2a profiling (adjusts M4/M5 priorities):**
    `rx.input`'s 112 µs was MIS-ATTRIBUTED in §2a — ~78 µs is its el-input `create()`
    override building a `ternary_operation` Var per call (forms.py:457 →
    `var_operation` wrapper), shared by both paths and untouched by construction work.
    `rx.button(on_click=…)`'s 157 µs is dominated by `EventChain.create` itself —
    exactly M4's target (cache parsed arg-specs per (class, trigger)).
  - ~~Phase 2b: `push_node` + staged nodes + the seal.~~ **SUPERSEDED by phase-2a
    measurement (2026-06-11).** The staged seal's value was predicated on replacing
    per-node Python reads — but the freeze's prop reads were already reduced to
    `read_field` dict probes + native-var struct reads (tasks B and #10), so staging
    props in Rust saves only ~100-200 ns/prop on the props slice (13% of an ~9 ms
    freeze), against substantial implementation bulk, the write-through/invalidation
    protocol, and byte-risk. Should it ever be revisited: mirrors are complete
    storage, so staged data can be a pure optimization layer with INVALIDATION (drop
    `_arena_idx` on doubt) instead of write-through sync — and staging only js-prop
    values means the audited mutation surface (alias/style/children/custom_attrs —
    never js props) cannot desync it.
- **M4 — Event optimization. DONE (2026-06-11).** `create_event_chain_fast`
  (event/__init__.py): for `EventHandler`/`EventSpec` values, reuses
  `_parse_args_spec_cached` (parsed placeholder-arg Vars cached per spec object —
  id-keyed with the spec referenced, so ids stay claimed; specs are class-level
  constants) and skips the spec-vs-callback validation (`check_fn_match_arg_spec`,
  `_check_event_args_subclass_of_callback`, `get_type_hints` walks — raise/warn only);
  all other shapes delegate to `EventChain.create` unchanged. Used only by the arena
  mirror; runtime `EventChain.create` untouched. Measured: chain build 10.7 → 4.5 µs
  (2.4×); `rx.button(on_click=<stable handler>)` 42.3 → 19.6 µs (2.2×). Note: the
  plan's "rx.input 112 µs" was mis-attributed — see the phase-2a finding; chain
  assembly was already Rust (`assemble_chain_js`), so the remaining win was exactly
  parse-caching + validation skip. Gate: fork-pair docs diff 427/427 byte-identical
  (shared cached arg Vars shift no bytes); parity suite 21 fixtures; oracle 27/27.
- **M5 — Default-on + measure + cleanup. DONE (2026-06-11).** `REFLEX_ARENA_CONSTRUCT`
  is now kill-switch semantics (default ON under the Rust pipeline; `=0` restores
  `_post_init` everywhere). Denylist audit: none needed — memo classes self-exclude
  via the `_post_init`-is-base check, and the fork-pair 427/427 gate ran with zero
  denylist entries. `bench_push_node` scaffolding stripped from session.rs. Measured
  reality vs the §5 projection: docs cache-off wall time is ~35-41 s and EVALUATION-
  dominated (docgen markdown + demo exec); construction savings (~83k in-scope nodes
  × ~10-20 µs ≈ 1-1.5 s) are real but inside this container's ±7 s run variance — the
  reliable numbers are the per-call factors (text 1.9×, style 1.3×, events 2.2×) and
  the 88% fast rate. The "~4 s target" assumed the staged seal zeroed the freeze; that
  path is superseded (M3 note) and the freeze remains ~9 ms/page from prior waves.

## 4a. Post-completion extension (owner-directed, 2026-06-11): immutable components + native var-harvest consumption

Owner decision: stage construction data toward Rust ("method 1") and make components
immutable. Profiling after M5 showed the dominant remaining Python/isinstance slice is
the FREEZE calling `_get_vars` per node (hooks/imports VarData harvest): ~991k calls,
6.5 s cum profiled, 1.09 M isinstance, 139 k LiteralVar creates, ~0.96 M abc checks.
Key reframing: post Var-cutover, every var's `VarData` already lives in Rust memory —
"sending the data to Rust" reduces to priming the existing `_vars_cache` tuple (the var
HANDLES) at construction and letting the freeze read it natively from the instance
dict. No arena, no generations: the tuple is owned by the component; immutability
(enforced as invalidate-on-write) makes it authoritative.

- **Phase I — DONE (2026-06-11).** `Component.__setattr__` invalidation bridge: a write
  to any harvest-relevant field (props ∪ {style, special_props, event_triggers,
  class_name, id, key, custom_attrs}; per-class cached set) drops a staged
  `_vars_cache`; non-harvest writes (RadixThemes `alias` patch, DebounceInput method
  swaps, Form's submit handle) keep it. In-place container mutation inside `add_style`
  overrides is covered by the style fold calling `_clear_compile_caches` (which already
  pops `_vars_cache`). The mirror fast path primes `_vars_cache` at construction by
  running `_get_vars` (exact parity by construction — it IS the harvest code). Also:
  `create()`'s `_validate_children` is now skipped under the arena scope (raises only;
  321 k isinstance/compile). Gates: 24-fixture parity suite, fork-pair docs diff
  427/427 byte-identical, oracle 27/27, suites green.
- **Phase II — DONE (2026-06-11): freeze consumes `_vars_cache` natively.**
  Landed as specced below; measured outcome and the follow-up it exposed:
  `_get_hooks_internal` Python executions halved (276k → 143k calls, 4.06 → 2.69 s
  cum profiled; `_get_vars_hooks` 2.59 → 1.66 s), and the imports walk's per-var
  `_get_all_var_data` Python calls are gone for staged nodes. Remaining `_get_vars`
  frames split: 160k = the construction-time PRIMING itself (phase I runs the Python
  harvest once at create — i.e. staged nodes still pay the harvest, just earlier),
  81k+79k = el-forms classes overriding `_get_vars` (gated out by design), and the
  rest = event/ref-bearing nodes (hooks gate) and rich/invalidated nodes.
  **Next refinement: build the staged tuple directly from mirror-held values**
  (prop vars, style var_data, chain vars are all in hand in `_arena_mirror_kwargs`)
  instead of running `_get_vars` — kills the priming double-pay. Requires the
  class-default-Var handling analyzed earlier: per-class precomputed default prop
  vars (defaults are class-level; factory-produced Var defaults make a class
  ineligible). Gates: oracle 27/27; 40 parity fixtures; fork-pair docs diff
  **427/427 byte-identical** with the native branch live; suites green (known 6).
  Original spec follows. In freeze.rs, the two
  `_get_vars` consumers are `read_hooks_internal` (freeze.rs:1843 →
  `_get_hooks_internal` → `_get_vars_hooks`, component.py:2372) and
  `build_imports_dict`'s var-imports step (`_get_imports`'s `var_imports`,
  component.py:2287). `_get_hooks_internal` (component.py:2465) composes, in merge
  order (later wins): `_get_events_hooks()` + ref hook + mount-lifecycle hook +
  `_get_vars_hooks()` — and the freeze ALREADY derives ref presence and lifecycle
  natively (the `_REF_HOOK_IMPORTS`/`_LIFECYCLE_HOOK_IMPORTS` wave), so the port is:
  events hooks (from the frozen chains) + the staged-tuple vars hooks. Branch: probe
  the instance dict for `_vars_cache` (same `instance_dict` helper as read_field);
  when present AND the class's `_get_vars`/`_get_vars_hooks`/`_get_hooks_internal`
  are base implementations (forms.py:266 overrides `_get_vars`!) AND every cached var
  passes the `native_var` gate AND its `var_data.components` is empty → iterate the
  tuple natively, fold `var_data.hooks` (dict vs set semantics per component.py:2381)
  and `var_data.imports` in Rust, skip the Python calls. Anything else → existing
  Python path (which re-primes the cache). Expected: the 6.5 s cum slice and the
  isinstance/abc storm collapse to native struct reads. Gate as always: fork-pair
  427/427 + oracle + suites.
- **Phase III — owner follow-up: full immutability enforcement.** Deprecate (then
  refuse) post-create writes to harvest fields; migrate the remaining internal
  mutators (Upload's `special_props` assignment → construct-final; radix Progress's
  in-place `custom_attrs` update inside `add_style`; the style fold's `self.style`
  assignment is framework-internal at seal time and either stays exempt or moves
  fully into the freeze). Breaking-change policy (console.deprecate + fallback)
  applies.

## 4a-bis. push_node v0 design (the mirror's Rust fast lane, 2026-06-12)

The last framework slice: `_arena_mirror_kwargs` + `_arena_build_vars` (~5 s cum
profiled / 73k nodes). v0 ports the DOMINANT call shape only — every kwarg is a
schema PROP and every value is a native Var or an exact-type literal
(`bool/int/float/str/NoneType/list/dict/tuple/set/Decimal/date/datetime` — the
RustLiteralVar dispatch tuple at vars/base.py:1426) — anything else returns None
and takes the Python mirror unchanged.

- Rust: module-level pyfunction `mirror_props(class_key, props: &PyDict) ->
  Option<(PyDict, PyTuple)>` + a GLOBAL schema registry (class ptr → schema +
  held class ref + per-class info: prop order, is_var flags, Var-valued
  defaults passed from Python at registration). Literal wrapping calls the SAME
  in-crate `RustLiteralVar.create` entry the Python dispatch calls — identical
  Vars by construction. Returns the mirror dict + the `_vars_cache` tuple
  (prop vars in schema order, Var-valued class defaults for unset props; no
  identity/style/event entries exist in this shape).
- Python: `_arena_create_eligible` registers the class (schema pieces + default
  vars) once; `_create` tries the native lane first, falls back to
  `_arena_mirror_kwargs`.
- Gates: the standard battery (oracle, parity suite, fork-pair 427, import-scope
  A/B under `all`), plus a direct equivalence test native-lane vs Python mirror
  per fixture (dict equality by key + per-var `_js_expr`/var_data presence).

## 4c-next. Program 2 — making framework overhead vanish (roadmap, 2026-06-12)

Measured end state of program 1: docs compile 59.5 s (pure Python) → 29.3 s; the
remaining ~23 s ≈ 12 s user docgen code + ~10 s framework. The ~10 s is no longer
"unported functions" — it is the structural cost of components/vars being Python
objects that per-node Python code (create() overrides, Var ops, mirror plumbing)
touches. Three stages, ordered by leverage per risk:

**Stage 1 — finish the current arc (incremental, every step fork-pair-gateable).**
1. ~~mirror v1: extend `mirror_props` to str class_name, raw base fields, and style
   keys~~ **DONE 2026-06-12.** The classification loop and var harvest run in
   Rust; the constructions whose semantics live in Python (`Style(...)`, the
   synthetic style `Var`, `VarData.merge`) go through cached refs to the same
   callables the Python mirror uses (`init_mirror_globals`) — identical by
   construction, still one `mirror_props` crossing per create call. Covered
   shapes: props (native/Python Vars + exact literals), str/joined/Var
   `class_name`, raw base fields, kebab special attrs, style kwarg
   (dict/list-of-dicts/Var/Breakpoints) + loose style keys, identity-prop
   f-string collapse. Events still fall back (the deferred chain-build item).
   Gates: oracle 27/27, fork-pair 427/427 ×2 runs, mirror parity suite (20
   fixtures incl. type-identity), pyright 321 baseline. Micro: special attrs
   2.0×, class_name 1.45×, id+key 1.5×, style keys 1.18×, style dict 1.15×
   (style shapes dominated by the Python `Style()` conversion — the remaining
   `convert()` port is the v2 follow-up below).
   v2 follow-up: port `convert()`/`format_style_key` (camel-case + shorthand
   expansion + recursive VarData merge) into Rust so style-bearing nodes skip
   the Python `Style` call too; then the Python event-chain build.
2. Flip `REFLEX_ARENA_CONSTRUCT=all` default (evidence already captured) + Phase
   III hard immutability (deprecate post-create harvest-field writes).
3. Literal/type completion in Rust: extend `RustLiteralVar` to Decimal/datetime/
   str-subclasses; port `figure_out_type`'s container recursion with var_type
   computed as Rust data (the `VarType` enum: Scalar/List/Dict/Union/Opaque).
   Expected: framework slice ~10 s → ~5-6 s.

**Stage 2 — handle-based components (the structural change; this is "push_node
full").** `rx.text(...)` constructs DIRECTLY into the Rust arena and returns a
handle holding only `_arena_idx` + children. No mirror dict; every compile-time
read comes from staged Rust data (the seal). The two prerequisites program 1
created: immutability (no write-through protocol needed) and the byte gates.
The key move: **per-node `create()` overrides become per-class declarative
transforms registered into Rust** (radix's alias patch = a registered rename;
rx.input's null-guard ternary = a registered value transform) — today they run
Python per node; registered transforms run in Rust per node. Var ops (.to,
ternary, f-string interpolation) complete the native var layer (no Python frames
around Rust data). Expected: framework slice → ~1-2 s, floor set by one PyO3
crossing per node (~0.3 µs × 150k ≈ 50 ms) plus the user's own page-function
Python.

**Stage 3 — don't pay at all (bigger than Rust for real workflows).**
1. Compile cache default-on + production-hardened (already measured: no-change
   rebuild 59×, one-edit hot reload 33×) — for the dev loop, framework overhead
   vanishes for every unchanged page regardless of language.
2. Rust-side parallel freeze+emit: with immutable handle components the per-page
   freeze/emit is embarrassingly parallel WITHOUT Python forks (evaluation stays
   serial Python; everything after is Send). The owner's objection to
   multiprocessing (complexity) doesn't apply to rayon inside the session.
3. Schema/eligibility registration at class-creation time (kill first-encounter
   probes).

Floor analysis: after stage 2+3, a compile costs (user page-function execution)
+ (~50 ms crossings) + (Rust work ≈ today's <0.5 s memoize+emit). For apps
without docgen-style evaluation, that is effectively "framework overhead
vanished"; for the docs app, what remains IS the app's own Python.

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

## 5. Projection vs measured outcome (docs app)

Original projection (P0): ~16 s → ~4 s, assuming construction ~7 s and the staged seal
zeroing the ~7.5 s freeze re-read. Measured outcome (2026-06-11, after M5):

- Per-construction: `_post_init` skipped for **88%** of in-scope docs constructions;
  per-call factors (full `create()`, incl. children normalization — not the bare-push
  P0 bench): text 1.9×, style-box 1.3×, input 1.3×, events 2.2×.
- The P0 construction-share estimate conflated `create()`-override work (e.g.
  rx.input's ternary Var, ~78 of its "112 µs") with constructor overhead; the
  removable slice was smaller than projected.
- Docs cache-off wall time ~35-41 s, dominated by docgen evaluation (irreducible user
  code) — construction savings (~1-1.5 s) are real but inside the measurement
  container's run variance. The freeze stays ~9 ms/page (prior waves' result); the
  staged-seal path that would have attacked it further is superseded by measurement
  (M3 note).

## 6. Kill criteria

Abandon (keeping P1's schema, which is useful regardless) if P2 shows: proxy reads appear
in a per-node-hot path we missed (>1 read/node average on base classes), or hybrid-tree
freeze grafting can't hold byte parity, or the write-through matrix exceeds the 28 audited
sites by an order of magnitude.
