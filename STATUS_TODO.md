# Status & TODO — compile perf program (2026-06-10)

## ACTIVE — the Python-reduction loop (owner goal, 2026-06-11)

Directive: profile → convert the biggest framework-Python slice to
Rust/native reads → byte-gate (oracle + fork-pair 427) → commit →
re-profile. Continue until only user overrides remain Python.

Program counters so far (docs compile, profiled, identical conditions):
total Python function calls **57.5M → 49.2M**; isinstance+abc
**3.35M → 2.24M**; `_post_init` 84.9k → 12.1k calls; `_get_vars`
frames 991k → 676k; LiteralVar creates 448k → 300k; `Style.__init__`
177k → 67k; the `_add_style_recursive` walk and per-var
`_get_all_var_data` calls eliminated.

Next targets, ranked by the live profile (/tmp/p2c.prof methodology —
`scripts/diff_arena_construction.py` is the byte gate; profile harness
pattern in the session transcripts: cProfile around
`rust_pipeline.compile_pages`, app import outside):

1. **Hooks-gate port for event/ref-bearing nodes** (the remaining
   `_get_vars_hooks` 170k frames + `_get_hooks_internal` fallback):
   port `_get_events_hooks` + the mount-lifecycle hook (chain rendering
   — reuse `assemble_chain_js`) + the ref hook string (`format_ref` is
   a string op) so `read_hooks_internal`'s staged branch also covers
   nodes WITH triggers/ids. Substantial; chain-render parity is the
   risk.
2. **forms.py:266 `_get_vars` override** (61k+ frames): el-form classes
   add extra vars; either port the override's contribution or stage it
   at construction via a per-class hook.
3. **`import_var` property** (143k Python calls + ImportVar builds in
   `build_imports_dict` step 3): pure function of (tag, alias,
   is_default) — value-keyed memo or native build. CARE: the property
   returns the Python `ImportVar` type; check type identity vs
   `RustImportVar` for downstream isinstance/merge consumers before
   swapping.
4. **First-freeze priming of import-time (docgen-cached) rich nodes**:
   their first freeze runs the Python harvest once; subsequent freezes
   hit the staged branch already. Optionally widen the arena scope to
   the whole compile (the 2.1k freeze-time foreach re-renders too).
5. Micro: `_post_init`'s setattr loop → dict update (290k Python
   `__setattr__` frames on the rich path); `BaseComponent.__init__`
   (112k calls, 0.62s profiled).

"User calls our fast Rust code" (the goal's second half) is already
the architecture: `Component.create` → mirror → staged tuple → native
freeze reads; the remaining Python per eligible node is the mirror
classification itself (~3.4s cum profiled for 73k nodes) — its Rust
port is the original plan's `push_node`, which becomes worthwhile only
after items 1-2 shrink the surrounding Python.



Companion to `RUST_PIPELINE_FINDINGS.md` (numbers + reasoning live there) and
`PARITY_ORACLE.md` (what the gate guarantees and what it doesn't).
Byte gate for every step: `uv run python scripts/parity_oracle.py check`
(PYTHONHASHSEED pin no longer needed — determinism verified cross-seed;
golden now in-repo at `tests/codegen_corpus/parity_golden.json`).

## Done

- [x] **Phase 0 — oracle + instrumentation.** Byte-parity oracle (`scripts/parity_oracle.py`,
  20 cases, golden at `/tmp/rust_parity_golden.json`); freeze sub-phase timers in
  `reflex_pyread::timing` read via `last_phase_timings_ns()`.
- [x] **Phase 1 — measured freeze wins.** Fresh profile (39% evaluate / 47% freeze / 14% rest).
  True freeze breakdown: style 38% / imports 35% / props 13% — overturned the stale audit.
  Landed empty-style short-circuit (freeze −9%). Refuted: get_event_triggers cache (no-op),
  build_imports_dict-is-a-pessimization, "skip unset props = 1.5ms".
- [x] **Phase 2 gate answered:** batched extractor is ~5% total — NOT transformative; skipped.
- [x] **Parallelism measured** (`scripts/measure_parallel_compile.py`): warm fork pool =
  **6.05× on 6 physical cores (perfect linear)**; threads useless (GIL); fork-per-build 4.3×
  at 65 pages. Output byte-identical; per-page results pickle cleanly.
- [x] **Salsa cache prototyped + measured** (`reflex/compiler/cache.py` + hook in
  `rust_pipeline.compile_pages`, `scripts/measure_cache_compile.py`): import-graph keys,
  disk store `.web/.rxcache/`. **Warm all-hits 59× (1730→29ms), 1-edit hot reload 33×**,
  cold-store overhead ~10%. 19 unit tests (`tests/units/compiler/test_cache.py`).
- [x] **Direction settled:** structural wins (cache + parallel) beat remaining single-thread
  tuning; only two Rust-side items still pay: (A) emotion port, (B) sparse `__dict__`.
- [x] **B foundation: descriptors cherry-picked** (`3472c420` from upstream/main, user's
  #6576): `ComponentField.__get__` non-data descriptor + sparse `BaseComponent.__init__`.
  Verified: `vars(component)` = 6 keys vs ~24; tests green (only the 6 pre-existing
  failures); full compile already 17.7 → **16.63 ms/route** (evaluate win).
- [x] **Oracle drift diagnosed + resolved:** sparse init changed import-harvest *multiplicity*
  only (one extra duplicate Text entry; page_js byte-identical). Oracle canon now dedups
  per-module entries (multiplicity is walk-internal, not an output contract); golden
  recaptured; check passes.
- [x] **Measured the expected freeze regression from descriptors:** unset-field getattrs now
  invoke Python `__get__` per node → freeze_total 5.5 → **14.3 ms** on the complicated page
  (style 5.3, imports 4.8, props 1.3). This is what B's freeze-side conversion removes.
- [x] **A groundwork:** complete `format_as_emotion` semantic map (source, helpers,
  breakpoints `["30em","48em","62em","80em","96em"]`, media-query rules, pseudo-selector
  rules, VarData propagation, ordering guarantees) captured via background agent — in the
  session transcript, summarized in findings §8-adjacent notes.

- [x] **Parity structure validated against React Compiler's Rust-port setup**
  (facebook/react#36173) and hardened — full writeup in `PARITY_ORACLE.md`:
  golden moved in-repo (the `/tmp` one was lost to a tmpfs wipe); cases added
  for root artifacts (`_document.js`/`theme.js`/`root.jsx` — same freeze.rs,
  previously ungated), page compile kwargs, and 3 style fixtures (breakpoints/
  pseudo/Var — the exact emotion-port surface); per-case `snapshot_stats` as a
  coarse intermediate-state check; determinism verified same-seed + cross-seed;
  corpus runner now asserts against page **+ memo bodies** (10 fixtures were
  silently checking the wrong artifact since memo promotion).
- [x] **Real emit bug found by that validation and FIXED:** any `id` prop made
  page/memo emitters write a hardcoded `const ref_root` line on top of the
  node's harvested ref hook — duplicate `const` (SyntaxError) for `id="root"`,
  dangling ref otherwise. Deleted the page-level emission (4 sites in
  `page_from_snapshot.rs`/`memo.rs`/`page.rs`) + the per-node `getattr("id")`
  needs_ref harvest (one fewer crossing/node). Golden recaptured; corpus
  21/21; units green (same 6 pre-existing failures).

## DONE — B: freeze reads sparse `__dict__` (task #8, 2026-06-10)

Landed, byte-identical (27-case oracle), tests green (same 9 pre-existing
failures across compiler/components/vars).

- [x] `pyo3_reader.rs`: `InternedAttrs.dunder_dict` + `m_default_value`;
      `PyRefs.component_field_cls`; `ClassMetadata.field_defaults:
      HashMap<String, FieldDefault>` with `FieldDefault::{Value, Missing, Dynamic}`;
      shared `instance_dict()` / `read_field()` helpers (probe instance `__dict__` →
      per-class cached default; `Dynamic` for any non-`ComponentField` descriptor).
- [x] Converted sites: `read_rendered_props` (prop loop + identity props +
      `custom_attrs`), `default_import_instance_is_trivial` (all field checks +
      prop loop), `build_imports_dict` (library/tag/event_triggers),
      `read_default_imports_summary_if_safe` (library/tag), `read_tag`
      (alias/tag/library), `import_alias_for` (library/tag/alias).
- [x] **Scalar defaults install as plain class attrs** (`_finalize_fields`):
      25 of ~32 fields skip the descriptor entirely — C-speed MRO lookup, same
      semantics. Descriptor kept only for factory defaults, no-default fields
      (AttributeError shadowing), and descriptor-valued defaults. Rust
      `class_field_default` caches plain class attrs as `Value`.
      Descriptor `__get__` calls: 6,166 → **657 per page**.
- [x] **Measurement-artifact resolved (the "5.5 → 14.3ms regression" was NOT real):**
      pre-descriptor Python measured with TODAY's wheel = freeze 11.91ms (not 5.5);
      the 06-08 "5.5ms" baseline came from an older wheel attributing less work to
      freeze spans. Apples-to-apples today: **freeze 11.91 → 11.47ms, full compile
      20.2 → 19.2 ms/page** — B is a modest net win, descriptors were never a
      2.6× freeze regression, and the "style-slice anomaly" doesn't exist
      (pre-descriptor also shows style ~4.8ms).
- [x] Where freeze time actually goes now (cProfile, per page): `_get_vars`
      Python ~7.5ms cum (called from hooks/imports paths), `format_as_emotion`
      ~4.1ms, `_get_hooks_internal` chain — i.e. **Python execution, not
      boundary chatter**. That is task A's exact territory.

## DONE — A: `format_as_emotion` in Rust (task #9, 2026-06-10)

Landed for the base `_get_style` path; override classes keep the Python callback;
structurally-unsupported inputs fall back to Python.

- [x] Rust transform in `freeze.rs` (`emotion_from_style` + `EmotionMap`):
      pseudo-selector formatting with exact `to_kebab_case` regex semantics,
      breakpoint lists + `Breakpoints` objects → `@media` maps (dict-comprehension
      key semantics, `setdefault().update()` merging, raw-subdict passthrough —
      NOT recursed, matching Python), `&:`-key special case, nested recursion,
      empty → None (renders `null` when nested), insertion order, Vars via
      `_js_expr` at render.
- [x] VarData propagation: deliberately NOT reproduced — verified the rendered
      output never consumed it on this path (style VarData reaches hooks/imports
      via `_get_vars`' synthetic style Var); byte-parity confirms.
- [x] `breakpoints_values` read live from the mutable global list (held by
      identity — `set_breakpoints` mutates in place).
- [x] Gate: 27-case oracle byte-identical + NEW 12-case differential suite
      (`tests/units/compiler/test_rust_style_emotion.py`) asserting byte-equality
      with `LiteralVar.create(format_as_emotion(...))`.
- [x] Bonus: `_get_style`/`_get_imports` override identity checks cached per class.
- [x] Measured: style slice 4.6 → **3.0 ms**, freeze ≈ 11.2 ms, full ≈ 18.2 ms/page;
      stage split **17.7 → 14.72 ms/route** since program start.

## DONE — After A+B (2026-06-10)

- [x] Re-ran measurement matrix (stage split 14.72 ms/route; cache 27.8×/9.7× and
      pool 5.4× at the scripts' 17-page default) and updated
      `RUST_PIPELINE_FINDINGS.md` §11 + memory.
- [x] ruff clean on touched files; full unit suite green (9 pre-existing failures:
      6 compiler + 3 vars/test_object[Base]).

## DONE — Native-Var direct struct reads (task #10, 2026-06-10)

Owner's correction taken: "Rust port" means the DATA crosses into Rust, not
Rust walking Python objects. First leg landed: after the Var cutover,
`RustVar.js_expr` and the whole `VarData` tree already live in Rust memory —
freeze was reading them through the Python attribute protocol
(`getattr("_js_expr")` → getter → PyString alloc → copy; `_get_all_var_data`
→ full VarData clone + wrapper + getattr storm per bucket).

- [x] `reflex_pyread` now depends on `reflex_vars`; `RustVar` exposes
      `js_expr_str()` / `var_data_ref()` for in-process readers.
- [x] `native_var()` in freeze.rs: downcast to the pyclass + per-class cached
      safety gate (exact `RustVar`, or subclass whose `_js_expr` /
      `_get_all_var_data` descriptors are the base ones — overrides keep the
      Python path).
- [x] Converted: `render_value_as_js`, `render_style_value`,
      `register_var_data` (replicating the `PyVarData` getter surface exactly:
      imports pairs empty, components empty, position None, dep str = js_expr),
      `var_has_reactive_data`, `var_has_imports`.
- [x] `build_imports_dict` step 1 gated on `lib_dependencies` emptiness
      (read_field probe) — skips the `_get_dependencies_imports` Python call
      for almost every node.
- [x] Gate: oracle 27/27 byte-identical; same 9 pre-existing failures.
- [x] Measured: freeze 11.2 → **~9.2-9.9 ms**, full **18.2 → 16.4 ms/page**
      (best-of), stage split **14.42 ms/route** (program start: 17.7).

## Full-system-port roadmap (the remaining Python in freeze)

In order of measured value; each wave moves DATA into Rust, not just compute:

- [ ] **Port `_get_vars` to Rust** (~7.5 ms cum/page across imports+hooks
      callers): enumerate prop Vars via `read_field` + native downcasts, style
      synth-Var from `style._var_data`, special_props, identity props with
      f-string collapse. Blocker pieces: `_get_vars_from_event_triggers`
      (EventChain) and `LiteralVar.create` f-string collapse — keep those as
      callbacks first, port last.
- [ ] **Port `_get_hooks_imports`**: ref hook (= id set), mount lifecycle
      (on_mount/on_unmount triggers), then hooks var_data imports via native
      `VarData` reads. `_get_hooks`/`add_hooks` overrides stay callbacks.
- [ ] **Endgame**: Component field storage Rust-side (a Rust-backed store
      written at construction) so freeze stops walking Python objects at all
      — evaluate writes in, compile reads Rust. This is the actual "full
      system port" and supersedes per-site conversion.

## DONE — docs-app compiles under `run-rust` (2026-06-10)

Gate set by owner: the docs app (`docs/app`, 427 pages incl. enterprise/site-shared
demos) must compile before pool/cache productionizing. Achieved:
**`rust-compiled 427 page(s) in 19.7s` cold, 9.6s second run** (demo pages that
register State classes pin uncacheable, by design). Six cutover bugs fixed, each
with a failing-first regression test in `tests/units/vars/test_rust_var_cutover.py`
/ `test_cache.py`; oracle 27/27 byte-identical throughout; the 3 pre-existing
`vars/test_object[Base]` failures are now FIXED (9 known failures → 6):

- [x] TypedDict item access kept the dict type (TypedDict subclasses dict ⇒
      Mapping branch; no `__args__` ⇒ fell back to receiver type) — `is_typeddict`
      gate in `object_attr_type` (py.rs).
- [x] Bare-`dict` item access same fallback — mapping branch now uses
      `_determine_value_type` (`Any` when bare).
- [x] `ObjectVar` marker lost `__getattr__`/`__getitem__` ⇒ all `.to(ObjectVar)`
      casts broke (rx.scroll_to) — marker delegates to a RustVar built from self.
- [x] `.to(FunctionVar)` returned a native var with no `__call__` ⇒
      `getattr(api, name)(*args)` (rxe PassthroughAPI) broke. NOT fixed with a
      RustVar `__call__` (made `callable(var)` true everywhere; broke
      dep_tracking's callable-vs-var dispatch — 34 failures). Rust `to()` now
      delegates function-class casts to Python `Var.to` ⇒ callable ToOperation.
- [x] Underscore string keys (`["_zoom"]`, rxe map events) refused — only
      dunders are refused now (matches pre-cutover ObjectVar).
- [x] `ObjectVar.get(key, default)` dropped in cutover — restored on RustVar
      (cond(value, value, default)).
- [x] Event-chain entries that are spec-TYPED Vars (rx.cond of two EventSpecs)
      mis-dispatched via `hasattr(es, "handler")` (true for spec-typed vars after
      attr fix) — both the assembler and var_data gatherer now discriminate by
      `isinstance(es, EventSpec)` / `var_isinstance(es, FunctionVar)`; other Var
      events render invocation-wrapped (matches pre-cutover
      `invocation.call(LiteralVar.create([event]), ...)`).
- [x] Public shims: `reflex.vars.function` re-exports ARRAY_ISARRAY /
      JSON_STRINGIFY / PROTOTYPE_TO_STRING; `map_array_operation` restored in
      base.py + `reflex.vars.sequence` (used by reflex-site-shared headings).
- [x] Cache `put()` crashed the build on unpicklable artifacts (DataEditor's
      method-local Portal app-wrap class) — now pins the route uncacheable.
- [x] Fixed pre-existing build break: `timing.rs` missing initializer fields
      (interrupted edit; stale `.tmp` file removed).

## DONE — docs-app RUNS under `run-rust` (2026-06-10, follow-up to the compile gate)

`reflex run-rust` (no flags) exited silently right after "Starting Reflex App".
Root-cause chain (strace + in-process CLI tracing):

- [x] **sys.path duplication kill** — `prerequisites.get_app` did
      `sys.path.insert(0, getcwd())` unconditionally; the legacy memo compiler
      (`compile_experimental_component_memo` → `_app_style()` →
      `get_and_validate_app()`) calls it once per memo ⇒ 5,649 duplicate
      entries (~400 KB) ⇒ the Py3.14 forkserver's `-c` cmdline (embeds
      sys_path) exceeded the kernel argv limit ⇒ `execve` **E2BIG** ⇒
      `BrokenPipeError` ⇒ click treats EPIPE as closed-stdout ⇒ **silent
      exit 1**. Fix: insert only if absent (prerequisites.py) + regression
      test `tests/units/utils/test_prerequisites.py`. (Note: `CI=1` is
      required for the docs app — reflex-enterprise exits "must be logged
      in" otherwise; the CI env var gates that check.)
- [x] **Hook-scope leak broke enterprise/drag-and-drop at runtime** —
      page hook emit (`bucket_hooks`) iterated ALL arena nodes flat, so
      memoized candidates' own hooks (rxe dnd's `useDrop` declaring the
      class-constant `dropTargetCollectedParams`, ×9) landed in the page
      function alongside their memo bodies ⇒ duplicate `const` ⇒ vite
      PARSE_ERROR 500. Fix (hooks_emit.rs): hooks belong to the scope whose
      JSX references them — page walk = reachable-from-root with wrapper
      substitution (redirected node's own hooks → its body; children still
      render at the call site); body walks get the same rule for NESTED
      memoized descendants; match-arm side-table roots included. Oracle
      diffs were pure leak-removals (3 cases); golden recaptured.
      Regression tests: `tests/units/compiler/test_rust_memo_hook_scope.py`.
- [x] Verified end-to-end: `App running at :3000/docs`, backend `/ping`
      pong, enterprise/drag-and-drop + react-flow pages HTTP 200.
- [x] **Arena memo wrappers were never imported** — pages/bodies referenced
      `<X>_memo_<hash>` in JSX but no `import { X } from
      "$/utils/components/X"` was emitted (browser
      `ReferenceError: Div_memo_… is not defined`; invisible to curl — SPA
      shell returns 200). Fix: `wrapper_imports()` in page_from_snapshot.rs
      — each module imports exactly the wrappers its rendered scope
      references (same redirect-substituting walk as the hooks fix); a body
      never imports itself. Oracle diff purely additive imports; golden
      recaptured. Verified down to the vite module graph: page module's
      rewritten wrapper import URL serves 200; 0/427 pages have
      unimported wrapper refs. NOTE: memo hashes are process-scoped
      (subtree_hash folds interned Symbol ids) — names differ across
      builds but are consistent within one; fine since bodies are
      rewritten each build.
- [x] **Cache served stale pages across compiler rebuilds** — manifest was
      keyed on Reflex version only; after `maturin develop`, hits replayed
      pages from the old emitter (masked the import fix). Manifest now
      carries a stat fingerprint of the `_native` extension
      (`_compiler_fingerprint`); any rebuild invalidates the whole cache.
      Test: `test_compiler_rebuild_invalidates_manifest`.
- [x] **"One-shot" legacy rebuild ran on EVERY `run-rust` (~44s/run)** —
      the gate checked `.web/utils/components.jsx`, a memo barrel index the
      MEMOS redesign removed entirely (nothing writes it), so the fallback
      never stopped firing. Two-part fix: (1) implemented the noted TODO —
      `rust_pipeline.compile_pages` now emits the `@rx.memo` modules itself
      via `compile_memo_components(MEMOS.values())` and folds their imports
      into the bun set (test: `test_rust_pipeline_memos.py`); (2) the gate
      now checks only `root.jsx` (which the Rust pipeline writes), so the
      legacy compile fires at most once per fresh `.web`. Docs run-rust:
      ~58s → ~15s (compile-only verified: no rebuild, DocsNavbar.jsx
      written by the rust phase). `test_arena_end_to_end_no_legacy_calls`
      updated: memo emission is a deliberate legacy-helper reuse, stubbed
      there to keep isolating the page/app-root path.

## DONE — `@rx.memo` emission ported to Rust (2026-06-10/11)

Owner's correction taken mid-port: strings in, strings out — ONE crossing
per artifact, no Python re-assembly of Rust-produced parts. The result:
`CompilerSession.compile_rx_memo_arena(component, name, signature, path)`
— freeze + full module assembly in Rust (legacy `memo_single_component_
template` byte shape), file written Rust-side, imports dict back for bun.
The single Python callback is `_format_memo_imports` (header formatting
over the harvested ImportVar dict — same pattern as app-root/doc/theme).
Python glue: `prepare_memo_component_for_compile` + `memo_component_
signature` (shared with the legacy path), dispatch in
`rust_pipeline.compile_pages` — plain component memos → arena; passthrough
+ function memos stay legacy (root-only/string renders, nothing to port).
Memo-chain hook bucketing matches legacy `_get_all_hooks` (`render_hooks_
rx_memo`: INTERNAL entries join PRE — legacy reports them positionless).

**Gate:** differential tests vs the legacy compiler
(`test_rust_pipeline_memos.py`) + an at-scale sweep over ALL 29 docs-app
component memos: **11 byte-exact, 18 identical modulo import-line order,
0 real diffs**. The legacy emitter remains the oracle.

**The sweep exposed SIX pre-existing freeze/emit bugs affecting PAGES too**
(corpus never caught them — its golden is rust-captured, and fixtures
happened to dodge each):
- [x] foreach callback args hardcoded `(item, index)` while bodies
      reference the real names (fixtures all used `lambda item:`) — args
      now frozen from the IterTag (`control_flow.foreach_args`).
- [x] Match emitted `match_template(...)` — a runtime helper that does
      not exist (every rx.match page died with ReferenceError) — both
      emitters now emit the legacy switch-IIFE.
- [x] Match condition groups (`(conditions_list, body)`) rendered as one
      list-typed case ⇒ `JSON.stringify(["x"])` never matches ⇒ all
      matches fell to default — freeze iterates inside the group.
- [x] `add_custom_code` MRO chain never harvested (docs heading-anchor
      slugify code missing from every page) —
      `control_flow.custom_code_extra` + per-class chain-empty gate.
- [x] `_exclude_props` ignored ⇒ junk props (`items:[]`,
      `listStyleType:"none"` on lists; `dropRef`/`onDrop` double-wired on
      dnd) — excluded in props/identity/custom_attrs/event readers,
      per-class identity gate.
- [x] `special_props` spreads dropped entirely (`...{...searchBarProps}`)
      — frozen into `control_flow.special_props`, emitted after keyed
      props in both emitters.
- [x] **General fix for imperative `_render` overrides** (Form's
      `handleSubmit_*` swap, Theme's css injection — 32 overrides/19
      classes): `render_is_base` per-class gate; override classes source
      props/events/spreads from the rendered Tag (legacy-exact), base
      classes keep the fast raw-field path.

Oracle golden + corpus recaptured (diffs = the real fixes + hash-derived
memo-name churn). Perf note: rx.memo emission now costs one freeze per
memo instead of the legacy `render()` + four `_get_all_*` tree walks.

## Profile of the docs compile (2026-06-11) — where the "rust phase" time goes

cProfile + instrumented split of `compile_pages` on docs/app (427 pages,
warm cache, 288 uncacheable):

| slice | time | nature |
|---|---|---|
| evaluate | ~10s | docgen markdown + demo exec for the 288 State-registering (uncacheable) pages |
| arena freeze | ~7.5s | per-node Python callbacks (see below) |
| rx.memo arena emission | 0.2s | (was ~4.5s via the legacy helper) |
| keys/statics/writes | ~3s | |
| actual Rust memoize+emit | <0.5s | never the bottleneck |
| app import (before the phase) | ~8s | docgen parses all markdown at import |

**Stupid things found (quantified):**
- [x] `isinstance` 11.5M calls/compile, 5.6M through abc `__instancecheck__`
      (RustVar is a REGISTERED Var subclass ⇒ every `isinstance(x, Var)` is
      the abc slow path). Fixed the top sites with exact-type fast paths
      (`_get_vars` via `_is_var`, the two `LiteralVar` dispatchers — which
      also allocated a reversed list copy per call, 384k copies):
      **isinstance −45%, abc −55%**, byte-identical output.
- [x] **Hooks chain runs ~2×/node in the freeze** — FIXED (2026-06-10
      "fix all"): `build_imports_dict` step 2 no longer calls
      `_get_hooks_imports`; ref/lifecycle hook imports come from
      module constants (`_REF_HOOK_IMPORTS`/`_LIFECYCLE_HOOK_IMPORTS`
      via PyRefs), `_get_hooks`/`_get_added_hooks` var_data imports are
      pulled through `call_cached0` + skip-lists, and
      `event_triggers_field` is read once and shared with step 4.
      `_get_hooks_imports` calls: 144k → 2.6k (residual = legacy
      passthrough/function-memo path). Oracle 27/27 byte-identical.
- [x] `compile_pages` app-wrap PYTHON tree walk — FIXED:
      `collect_app_wraps` in the freeze harvests
      `_get_app_wrap_components` per CLASS (identity-gated via
      `app_wrap_is_base`, expanded dict cached on `ClassMetadata`,
      merged once per class per freeze) and
      `compile_page_from_component_arena` returns the dict as a 4th
      tuple element. `_get_all_app_wrap_components` is GONE from the
      compile profile (was 139k visits / ~1.3s). `_app_root` deepcopies
      wrappers before mutating, so per-class instance reuse is safe.
- [x] `_add_style_recursive` — FIXED with a per-class gate: skip the
      fold when the class has no `add_style` MRO chain (cached) AND
      `App.style` has no entry for the class AND the instance style is
      a dict (the fold then only rebuilds `self.style` from itself).
      Docs compile: only 5.8k of 266k node visits still fold (2.2%),
      cumulative 1.15s → mostly recursion frames (was ~2.2s all-fold).
      3.1× on a synthetic all-base tree. Full P1 style-fold stays parked.
- [x] The render-tag fallback — MEASURED (cache-off full docs compile,
      probes on all 15 `_render` overrides): 1,374 calls, **66 ms
      total, 0.3% of the 19s compile** (radix primitives 25ms, Form
      19ms, Theme 11ms). Porting Form/Theme rules to Rust would save
      ~30ms — NOT warranted; keep the tag path for all overrides.
- ~~The macro lever remains the fork pool (6.05× measured)~~ SUPERSEDED
  2026-06-11: owner — multiprocessing existed before and was REMOVED
  (complexity, no win for normal apps); do not resurrect. New macro
  lever: **arena-born construction** — see `arena_construction_plan.md`
  (P0 proof done: bench 46µs→0.63µs per node (73×), 90-finding audit,
  design fixed; `bench_push_node` prototype lives in reflex_py
  session.rs). Measured: only ~16% of evaluate is truly user code.

## DONE — arena construction M1: per-class construction schema (2026-06-11)

Inert foundation for `push_node` (plan M3). `ConstructionSchema` on
component.py mirrors `_post_init`'s kwarg classification (trigger >
prop[is_var] > invalid-on_* > field > special-attr > style), built once
per class from `get_props` + per-field `type_origin is Var` +
`get_event_triggers` + merged `_rename_props`, cached on the class
`__dict__` (the `_event_triggers_cache` pattern).
`CompilerSession.register_class_schema` stores the table on
`ClassMetadata.construction_schema`; `class_schema_classify`/
`class_schema_rename_props` are the differential-test hooks. Nothing in
the compile path consumes it yet.

- Gate: schema vs literal `_post_init`-transcription sweep across ALL
  loaded Component classes (>200; core/radix/lucide/markdown/sonner/
  code) × full per-class name universe + synthetic edge names;
  behavioral spot checks driving `create()` per category; Rust
  round-trip classify equality; cargo classify tests. New files:
  `tests/units/reflex_base/components/test_construction_schema.py`,
  `tests/units/compiler/test_construction_schema.py`.
- Oracle 27/27 byte-identical; unit suites green (same known 6);
  pyright/ruff clean on touched files; docs app 427/427 pages compile
  in-process (19.6s cold, matches baseline).
- Env note (fresh containers): bootstrap order is `uv sync
  --no-install-package reflex` → `uv pip install maturin
  uv-dynamic-versioning editables` → `maturin develop --release` →
  `uv sync --inexact --no-build-isolation-package reflex` (the reflex
  hatch hook imports reflex_compiler_rust, so isolated builds fail).
  Full `make_pyi` regen drifts 16 hashes on a CLEAN tree here
  (environment drift, not committed).

## DONE — arena M2: style fold moved into the freeze (2026-06-11)

The Rust pipeline no longer runs the Python `_add_style_recursive` tree
walk. `compile_unevaluated_page(apply_style=False)` marks the fold root
(`_style_fold_root` instance attr — exactly the pre-Fragment/meta
subtree); the freeze replicates the legacy per-node GATE in Rust
(per-class add_style-chain + `_add_style`-base via `class_bool_flag` on
`ClassMetadata.style_fold_base`; per-class-per-freeze App.style entry
probe in `PyRefs::style_fold_entries`; per-node style-is-dict) and calls
the extracted Python `Component._apply_style_fold` for folding nodes
only (~2% on docs). Fold propagates along children edges only: match
arms/default fold (alias `self.children`), foreach bodies do NOT (the
freeze re-renders them fresh via `render_component()` — legacy bytes
never saw folded foreach bodies; pre-existing rust-vs-`reflex run`
divergence, NOT introduced here). `app.style` rides
`compile_page_from_component_arena(..., app_style=)`. Kill switch
`REFLEX_STYLE_FOLD=0` restores the Python fold.

- Gates: oracle 27/27; unit suites green (same known 6); 16-fixture
  differential suite `tests/units/compiler/test_rust_style_fold.py`
  (incl. end-to-end fold-on vs fold-off `compile_pages` byte equality);
  docs per-page A/B over 427 pages: 426 byte-identical, data-editor
  fails its own legacy A/A (random `getData_*` hook names; pinned
  uncacheable anyway).
- Measurement notes: docs compile cache-off ~48s fold-on vs ~45-61s
  fold-off across runs — evaluation noise dominates; the fold's ~1.15s
  of recursion frames is the expected win, and the architectural point
  is M3 readiness (arena nodes never need `.style` Python reads).
- Diff-harness findings (will matter for M3's gates):
  - Docs compiles are NOT byte-comparable across processes OR across
    re-evaluations in one process (state-name counters, memo symbol
    churn). Per-page A/B must evaluate ONCE and deepcopy per side.
  - Both sides must be deepcopies: memo `subtree_hash` is sensitive to
    set-rebuild iteration order (original-vs-its-copy churns memo names
    with byte-identical normalized output).

## DONE — arena M4 + M5: events fast path; arena default-ON (2026-06-11)

**M4:** `create_event_chain_fast` + `_parse_args_spec_cached`
(event/__init__.py, exported via EventNamespace): parsed placeholder-arg
Vars cached per spec object (id-keyed, spec referenced so ids stay
claimed; specs are class constants), spec-vs-callback validation skipped
(raise/warn only); non-handler shapes delegate to `EventChain.create`.
Used only by the arena mirror — runtime EventChain.create untouched.
Measured: chain build 10.7 → 4.5 µs (2.4×); `rx.button(on_click=
<stable handler>)` 42.3 → 19.6 µs (2.2×).

**M5:** `REFLEX_ARENA_CONSTRUCT` flipped to kill-switch semantics
(default ON under rust_pipeline; `=0` restores `_post_init`). Denylist
audit: none needed (memo classes self-exclude; fork-pair 427/427 ran
with zero entries). `bench_push_node` scaffolding stripped from
session.rs (+ unused imports). The plan doc now records the measured
outcome vs the P0 projection and formally supersedes the staged-node
seal (M3 phase 2b) by measurement.

- Gates: oracle 27/27; suites green (known 6); parity suite 21
  fixtures; fork-pair docs diff 427/427 byte-identical post-flip;
  cargo tests green; docs compile smoke 427/427 with arena default-on.
- **Newly observed PRE-EXISTING pollution pair** (not from this work;
  verified present with arena code stashed):
  `tests/units/components/test_memo.py` followed by
  `tests/units/test_event.py::test_call_event_handler` →
  "DID NOT RAISE TypeError" — a component-memo registration makes
  `LiteralVar.create(<function>)` succeed process-wide afterward.
  test_event passes 100/100 in isolation. Same family as the
  DynamicState pollution: global-registry leakage between test modules.

### M4 scoping notes (superseded by the DONE above)

`EventChain.create` measured at **46 µs/trigger** (single-spec on_click,
stable handler): `call_event_handler` is 77% of it — roughly 28 µs
building the spec's args (`add_args`/`with_args`/`parse` Var
construction; deterministic per args_spec → cacheable) and 18 µs
`_check_event_args_subclass_of_callback` + `get_type_hints` (spec-vs-
callback type VALIDATION → skippable under the arena flag, same policy
as `satisfies_type_hint`). Cache keys must be identity-based on STABLE
objects only: EventHandler descriptors on state classes and class-level
arg-spec constants are stable; ad-hoc `EventSpec`s built per call
(e.g. `rx.console_log(...)` inline) are not — cache must not key on
those. NOTE: `EventChain.create` also runs at RUNTIME (event
processing) — any change must be gated or proven behavior-neutral, not
just compile-byte-neutral. Benchmark trap: `lambda:
rx.button(on_click=rx.console_log("x"))` times the console_log
EventSpec construction too (~100 µs of the 157 µs) — keep handler
construction outside the timed region.

## DONE — arena M3 phase 2a: full-surface mirror (2026-06-11)

`_arena_mirror_kwargs` now replicates `_post_init` end-to-end minus
validation: the exact Style merge (list-of-dicts, Breakpoints/Var
`{"&": ...}` wrap, css shorthand keys), special attrs kebab-cased into
custom_attrs (in-place on caller dicts), `EventChain.create` per
trigger, caller event_triggers dict copy, Var class_name passthrough.
Fallbacks left: unknown `on_*` (so `_post_init` raises), Var-bearing
class_name lists, malformed style shapes, memo classes (own
`_post_init`).

- Gates: 18-fixture parity suite (incl. error parity); fork-pair docs
  diff 427/427 byte-identical; oracle 27/27; suites green (known 6).
- Measured: in-scope fast rate 60.9% → **88.0%** (72.8k/82.7k).
  Per-call (full create(), incl. children normalization): text 1.9×,
  style-box 1.3×, input 1.3×, button-with-event 1.1×.
- **Mis-attribution found:** rx.input's "112 µs construction" is ~78 µs
  of its el-input `create()` override building a `ternary_operation`
  Var per call (forms.py:457) — both paths pay it; not construction
  machinery. Button events are dominated by `EventChain.create` — M4's
  exact target.

## DONE — arena M3 phase 1: construction fast path + gate (2026-06-11)

Default-off (`REFLEX_ARENA_CONSTRUCT=1` to enable). `arena_construction()`
contextvar scope in component.py, set by rust_pipeline around page
evaluation only. Eligible classes (`_post_init` is base + stock `Style`
factory; per-class cached) skip `_post_init` in `_create`: kwargs mirror
into the instance `__dict__`, Var-typed props `LiteralVar`-wrapped (Var
values pass through unchanged — `_create_literal_var` returns Var inputs
as-is), all-str class_name lists joined. Per-call fallback to
`_post_init` for event triggers, style inputs, special attrs, non-str
class_name, unknown names. Validation skipped on the fast path (the
documented flag-gated difference). No write-through needed yet — the
mirror IS the storage, so every audited post-create mutation site works
natively. M1's ConstructionSchema is the classifier.

- Gates: 16-fixture parity suite
  (`tests/units/compiler/test_arena_construct_mirror.py`); oracle 27/27;
  unit suites green (known 6); **fork-pair docs diff 427/427
  byte-identical** rich-vs-arena, zero errors.
- **Fork-pair harness (the M3+ gate tool):** fork twice per route from
  one imported parent; both children inherit identical random/counter/
  intern state, so single-page compiles are exactly byte-comparable —
  eliminates ALL evaluation nondeterminism (upload's random idents,
  data-editor, state counters, memo symbol churn). Normalization-based
  cross-process comparison was tried first and could not be made tight.
- Measured (docs, arena on): in-scope constructions 82.7k, fast 50.4k
  (**60.9%**); fallbacks are style-kwarg + event-trigger calls (phase 2
  and M4 cover those). Out-of-scope during compile: only 2.1k
  (freeze-time foreach `render_component()` re-renders — scope-widening
  candidates); ~233k constructions are app-import-time docgen, which
  stays rich by design (lifecycle audit).

### M2 scoping notes (kept for reference; superseded by the DONE above)

Construction-path facts established for M2, beyond the plan text:

- `theme` is DEAD in `_add_style_recursive` — threaded through the
  recursion, never used (the deprecated `_apply_theme` tail is gone).
  The freeze fold needs only `app.style`.
- **Fold scope is NOT the whole page tree.** `compile_unevaluated_page`
  folds the user component BEFORE `Fragment.create(component)` +
  `add_meta` wrap it — the outer Fragment and Title/Meta nodes are
  never folded by legacy. A freeze fold over all nodes would diverge
  whenever `App.style` targets Fragment/Meta classes. Exact scoping
  needs a fold-root mark (e.g. set by `compile_unevaluated_page` when
  `apply_style=False`) that activates folding for that subtree only.
- **Fold propagates along `children`-list edges only.** Legacy recurses
  `self.children`; prop-held components are never folded
  (`ApplyStylePlugin.enter_component` skips `in_prop_tree`). The freeze
  also pushes control-flow bodies and `_get_components_in_props` — the
  fold must not fire on push paths that don't correspond to a Python
  `children` entry (verify Match/Foreach/Cond body storage).
- **The per-node fold gate already exists in Python** (component.py
  fast path: style-is-dict AND no add_style MRO chain AND no App.style
  entry for type/`cls.create`) — only ~2.2% of docs nodes fold. The
  cheap M2 shape: replicate the GATE in Rust (class_bool_flag for the
  add_style chain; per-class-per-freeze App.style entry probe), and
  call one extracted Python helper (`_apply_style_fold`, the
  non-recursive portion of `_add_style_recursive`, single-sourced) for
  folding nodes only — byte parity by construction; the win is killing
  the Python recursion frames over the other 97.8%.
- Memo bodies (`prepare_memo_component_for_compile`) and the app-root
  path (`compiler/utils.py:333`) apply the Python fold separately —
  keep them; the freeze fold must not double-fold those trees (fold
  only under the explicit fold-root mark).

## DONE — "fix all" round on the profile findings (2026-06-10)

All four queued items above closed (see checkboxes for details). Docs
compile after the round: 19.0s cache-off / 16.0s warm-cache in-process
(427 pages; evaluate of the 288 uncacheable docgen pages dominates).
Gates: oracle 27/27 byte-identical throughout; corpus 21/21 (08_match
expectations refreshed — they pinned the old `match_template(` form the
switch-IIFE fix replaced; Rust-side test was updated at the time, the
fixture wasn't); cargo test green; new regression tests:
`test_arena_app_wraps_match_legacy_walk`,
`test_arena_app_wraps_empty_for_plain_tree`,
`test_arena_invokes_static_app_wrap_factory_once_per_class` (rewrote the
stale `test_arena_does_not_invoke_static_app_wrap_factories`, which
pinned the superseded "wraps stay in the Python walk" contract).

**Pre-existing failures observed, NOT from this round** (verified by
gate-revert + the failing frames being legacy-path code untouched here):
- The known 6 (dynamic-components ×2, markdown, import-fallback ×3).
- Full-suite-only pollution: pytest collection imports every test
  module, so `tests/units/test_app.py`'s module-scope `DynamicState`
  (computed var `comp_dynamic` reads the route-injected `self.dynamic`)
  registers globally; any test that then compiles full static artifacts
  (`_emit_static_artifacts` → `compile_state`) hits AttributeError —
  fails: test_cache ×3, test_rust_pipeline ×2, test_rust_pipeline_memos
  ×1, test_arena_followup ×1, test_app_wrap_* ×4, test_event ×1. All
  pass in directory-scoped runs. Root cause is test-state leakage into
  the global state registry, not compiler code.

## Parked / deferred (explicitly not now)

- [ ] **Full upstream/main merge** — 34 commits, 166 files; `app_wraps`-in-VarData (#6447)
      must be reconciled with the Rust `reflex_vars::VarData` (freeze harvests app_wraps);
      memo promotion + lucide per-icon imports will shift oracle goldens. Own work item.
- [ ] **Pool integration** into `compile_pages` (decision: cache first, then pool).
- [ ] **Cache productionizing**: cold-store ~10% overhead, dev-watcher driving `routes=`,
      Windows spawn for workers, REFLEX_COMPILE_CACHE docs.
- [ ] Freeze timers add ~1% overhead — feature-gate or strip before merge.
- [ ] Stale-route eviction in cache manifest (deleted pages accumulate; harmless).

## Working-tree state (uncommitted)

Modified: `freeze.rs`, `timing.rs`, `session.rs`, `pyo3_reader.rs`, `py.rs`,
`reflex/compiler/{rust_pipeline,session}.py`, `scripts/parity_oracle.py` (dedup canon).
New: `reflex/compiler/cache.py`, `tests/units/compiler/test_cache.py`,
`scripts/{measure_parallel_compile,measure_cache_compile,parity_oracle}.py`,
`RUST_PIPELINE_FINDINGS.md`, this file.
Committed this session: cherry-pick `0efad8c`-ish of `3472c420` (descriptors, #6576).
Corpus rename staged→unstaged: `tests/units/compiler/_corpus.py` (+ deleted
`test_arena_ir_completeness.py`) — was unstaged to allow the cherry-pick.
