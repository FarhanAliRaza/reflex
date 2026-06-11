# Rust compile pipeline — measurement-driven findings (2026-06)

**Supersedes `PROFILING_FINDINGS.md`**, which predates the arena cutover (`b7fc5898`)
and the Rust-Var cutover (`ee2a1719`) and is stale in its headline numbers
(`read_var_data 15µs/var`, `_get_imports 22%`, "Rust loses at scale", etc.).

Every number here is from a `perf_counter_ns` timer or the in-Rust phase timers
wired into the arena freeze this session. No estimates carried over from older docs.

Tooling produced this session:
- `scripts/parity_oracle.py` — byte-parity gate (page_js + memo bodies + imports) over
  the codegen corpus + the two heavy benchmark pages. `capture` then `check`.
- Arena freeze timers in `reflex_pyread::timing` (wired into `freeze.rs::freeze_into_slot`),
  read via `CompilerSession.last_phase_timings_ns()`.

---

## 1. Top-level profile (fresh)

Synthetic 8-route app, median **164 nodes/route**, **17.7 ms/route** full compile
(`scripts/profile_full_rust_compile.py 8 5`, `scripts/benchmark_stages.py synthetic:8 5`):

| Slice | Share | Where |
|---|---|---|
| `compile_unevaluated_page` — user code building the Component tree | **~39%** | Python (framework) |
| arena: freeze (PyO3 re-read) + memoize + emit | **~47%** | Rust (freeze dominates) |
| app_root + static artifacts + import-format + writes | ~14% | mixed |

- The Rust arena path is now **2.4× faster** than the legacy Python mechanical compile.
- `_get_imports` / `collect_all_imports_into` have dropped out of the top-20 — the
  "biggest remaining win" from the old doc is already done.
- Pure-Rust **emit + memoize are effectively free** (~24µs for 177 nodes; memoize is a
  single fused, pre-allocated pass). The Rust *core* is not the bottleneck.

**Core architectural shape:** we build a full Python `Component` tree (the 39%), then
re-walk it across PyO3 (~15-20 crossings/node) to rebuild it as the Snapshot IR (the
freeze, ~47%). The IR + codegen are excellent; the cost is the freeze re-read plus
constructing the tree in the first place.

---

## 2. Freeze internals (measured, the headline result)

`freeze_into_slot` was instrumented with per-sub-function leaf spans. Complicated page
(heaviest fixture), freeze_total ≈ **6.08 ms** before any change:

| Sub-function | ms | % freeze | Nature |
|---|---|---|---|
| `read_style` | 2.30 | **37.8%** | genuine Python execution (`format_as_emotion`) |
| `read_imports_summary` | 2.15 | **35.3%** | aggregation: gate + `build_imports_dict` |
| `read_rendered_props` | 0.81 | 13.3% | per-declared-field getattr loop |
| structural (class/classify/qualname/memo_mode) | 0.19 | 3.1% | cheap |
| hooks / optional / events | <0.25 | <4% | cheap |
| unaccounted (recursion/emit/loop) | 0.40 | 6.6% | — |

**This overturns the pre-session audit's ranking.** Style + imports dominate (73%); prop
iteration is third, not first. The audit (leaning on the stale doc) had "skip unset
props ~1.5ms" as the top pick.

### 2a. Style drill-down
- 275 styles on the page; **only 73 non-empty**. `format_as_emotion` costs ~**14.8µs per
  non-empty style** (pure Python, measured calling it directly). The 202 empty styles were
  each paying a `format_as_emotion` call + boundary crossing for nothing (~0.35ms wasted).
- Style is dominated by **genuine Python execution** — batching/marshaling tricks won't cut
  it; only porting `format_as_emotion` (emotion CSS semantics: pseudo-selectors,
  breakpoints, nesting) to Rust would.

### 2b. Imports drill-down
`read_imports_summary` splits into:
- **fast-path gate** (119 nodes, **7.41µs/node**, 0.88ms) — `default_import_instance_is_trivial`,
  which re-iterates props checking for var imports (redundant with `read_rendered_props`).
- **slow path** `build_imports_dict` (156 nodes, **8.58µs/node**, 1.34ms) — Rust reimpl of the
  base `_get_imports` aggregation (deps + hooks + library + events + per-var var_data +
  add_imports).
- The "fast" gate is nearly as costly per node as the slow path — it is not a cheap filter.

---

## 3. Hypotheses tested — measurement prevented two wrong moves

| Hypothesis (from the audit / old doc) | Verdict | Evidence |
|---|---|---|
| Cache `get_event_triggers` (uncached per-node dict build) is a win | **NO-OP** — reverted | cached vs cache-cleared construction: −1.8% / −4.8% (cached marginally slower). `args_specs_from_fields` is cheap. |
| `build_imports_dict` is a self-inflicted pessimization; just call `_get_imports()` | **REFUTED** — keep it | `_get_imports` first-call (uncached) = **10.5µs/node** > `build_imports_dict` 8.58µs. The Rust reimpl is a real ~2µs/node win. |
| "skip unset props ~1.5ms" is the top freeze win | **OVERSTATED** | real `read_rendered_props` = 0.81ms total; savable fraction is less. |
| `format_as_emotion` caching has "no profiling evidence" (critique) | **WRONG** | it is the **#1 freeze cost** (37.8%). |

**Lesson:** the pre-session audit's perf estimates (even after an adversarial critique
pass) were derived partly from the stale doc and were unreliable. Validate every claimed
win against the freeze timers + byte oracle before writing the optimization.

---

## 4. Landed change (validated, byte-identical)

**Empty-style short-circuit** in `freeze.rs::read_style`: on the base `_get_style` path,
after the override + whole-style-Var checks, return early when `self.style` is empty
instead of calling `format_as_emotion` on an empty dict. Safe because an empty dict maps
to empty emotion output (the transform loop never runs); only valid on the base path
(overridden `_get_style` may synthesize style from other fields).

- **freeze 6.08 → 5.55 ms (~9%)** on the complicated page; style slice 2.30 → 2.04 ms.
- Byte-identical across all 20 oracle cases; `tests/units/compiler` 238 pass
  (the 6 failures are pre-existing: import-fallback / dynamic-components / markdown).
- No effect on style-light pages (e.g. the stateful fixture).

---

## 5. Phase-2 gate decision — the batched per-node extractor

Premise: collapse the ~15-20 per-node PyO3 crossings into one `_arena_freeze_extract`
call per node (the stub already wired at `freeze.rs:494`, result currently discarded).

**Decision: moderate, bounded win (~0.8–1.2 ms/page ≈ ~15-20% of freeze, ~5% of total) —
NOT transformative.** Because the two dominant freeze costs are genuine Python *execution*
the extractor cannot remove:
- style `format_as_emotion` (14.8µs/styled node) — execution, not marshaling;
- import aggregation — `build_imports_dict` already minimized crossings by merging in Rust.

The extractor only removes the *marshaling between* per-node method calls. Worth doing only
if ~5% at moderate risk is wanted; otherwise freeze is near its cheap-win floor.

**Transformative freeze wins require porting `format_as_emotion` + the import aggregation
to Rust** (high build-correctness risk — these feed `style={}` and `bun install`).

---

## 6. Determinism (verified)

The compiler is **byte-deterministic across processes** even without a pinned
`PYTHONHASHSEED` — confirmed by capturing the oracle in independent processes and diffing.
Earlier apparent "drift" was two oracle bugs, both fixed: (1) `RustImportVar` has no stable
`repr` (address-bearing) — serialize by fields instead; (2) JSON round-trips tuples to
lists, so `memo_bodies` must be stored as lists. `collect_imports` / `collect_state_bindings`
push in observation order (HashSet only for dedup membership), so emit order is stable.

---

## 7. Recurring structural observation

Props/vars are traversed **2–3× per node**: `read_rendered_props`, the import triviality
gate (`default_import_instance_is_trivial`), and `build_imports_dict`'s `_get_vars`. Fusing
these into a single per-node pass is the main remaining structural cleanup on the freeze
side (cuts part of the 0.88ms gate cost + the prop re-iteration), independent of the
batched extractor.

---

## 8. Open decision (next direction)

Freeze cheap wins are largely spent (empty-style landed; the rest are <0.1ms each or need
big Rust ports). Options:
- **A. Port `format_as_emotion` + import aggregation to Rust** — biggest freeze gains, high risk.
- **B. Build the batched extractor** — ~5% total, moderate risk (see §5).
- **C. Drill the framework-construction 39%** (`compile_unevaluated_page`: `_post_init`,
  recursive theme styling, Var construction) — largest unexamined slice; deeper
  `reflex_base.Component` refactors are in scope per the owner's decision. Likely highest ROI now.

Recommendation: **C** — measure where construction time goes before committing to a big
freeze-side Rust port.

---

## 9. Page-level parallelism (measured 2026-06-09)

`scripts/measure_parallel_compile.py` — the per-page loop (evaluate → arena → write),
partitioned across workers. Box: Ryzen 5 5600, **6 physical cores** / 12 SMT threads,
Python 3.14.3 (GIL build). 65 pages, best of 5:

| Strategy | w=2 | w=4 | w=8 | w=12 |
|---|---|---|---|---|
| threads | 1.00× | 0.83× | 0.84× | — |
| fork per run (cold) | 1.65× | 3.51× | 4.11× | 4.34× |
| **persistent fork pool (warm)** | 2.00× | 3.78× | **5.62×** | **6.05×** |

- **6.05× on 6 physical cores = essentially perfect linear scaling.** SMT adds ~nothing
  (CPU-bound). The ceiling is core count, not the pipeline.
- Threads are useless on the GIL build (construction + freeze both hold the GIL);
  free-threaded 3.14t is the only way threads ever pay, and the Rust session is
  `unsendable` anyway (one session per worker regardless).
- Even fork-per-build (no pool) gets 4.3× at 65 pages — fork cost amortizes by ~30+ pages.
- **Byte parity verified:** pool output (pages + memo bodies) is byte-identical to
  sequential (`/tmp/check_parallel_parity.py`, 28 files sha256-equal).
- Integration cost is low: per-page results pickle cleanly (imports ≈ 11.6 KB/page,
  app_wraps, memo names, stateful flag all picklable), so workers can ship results to the
  parent over the normal Pool channel. Each worker needs its own `CompilerSession`
  (thread-affine pyclass). Caveat: `fork` start method is Linux/macOS; Windows would pay a
  spawn + app re-import per worker (one-time per build).
- **This beats every remaining single-thread optimization combined**: 6× vs the ~1.5–1.75×
  ceiling of the whole freeze/framework tuning program. Compile time becomes roughly
  `pages / physical_cores × 15 ms + statics`.

---

## 10. Salsa-style page cache (prototyped + measured 2026-06-09)

Prototype landed: `reflex/compiler/cache.py` (`CompileCache`) wired into
`rust_pipeline.compile_pages`. Pages are keyed by content hashes of their source module +
its transitive project-local imports (static `ast` scan, memoized per (mtime,size)) + page
metadata + mode + Reflex version. Hits skip evaluation + freeze + emit and replay stored
artifacts (jsx, memo bodies, pickled imports, app wraps). Pages whose evaluation mutates
global registries (State classes, bundled dynamic libraries) are pinned uncacheable.
Disk store at `.web/.rxcache/` survives process restarts. `REFLEX_COMPILE_CACHE=0` kills it.

`scripts/measure_cache_compile.py`, 65 file-backed complicated pages, best of 5:

| Scenario | ms | Speedup |
|---|---|---|
| no cache (today) | 1730 | 1.00× |
| cold build + store (once) | 1909 | 0.91× (≈10% first-build overhead) |
| **warm, all hits** (restart / no change) | **29** | **59×** (0.45 ms/page incl. statics) |
| **warm, 1 of 65 edited** (hot reload) | **53** | **33×** |

- The hit path is ~0.45 ms/page — imports merge + write_if_changed compare + statics; it
  amortizes better as the app grows (38× at 17 pages → 59× at 65).
- Hot-reload latency becomes `O(changed pages) + ~25 ms fixed`, not `O(all pages)`.
- Composes with the §9 pool: misses fan out to workers, hits are nearly free.
- Correctness: cache-hit output asserted byte-identical in `tests/units/compiler/test_cache.py`
  (19 tests: key invalidation by page/transitive-dep/metadata/base-dep change, unrelated-file
  immunity, relative imports, sticky uncacheable pins, blob pruning, persistence).
- Known soundness boundary (accepted, industry-standard): imports invisible to static
  analysis (computed `__import__`, `exec`) aren't tracked; kill switch + docs mitigate.

---

## 11. A + B landed (2026-06-10) — and a corrected baseline

Both remaining Rust-side items from §8 are in, byte-identical on the 27-case oracle
(now hardened — see `PARITY_ORACLE.md`), all tests green (9 pre-existing failures).

**B — sparse `__dict__` freeze reads.** `read_field` probes the instance `__dict__`
(only ~6 set keys post-#6576) and falls back to a per-class `FieldDefault::{Value,
Missing, Dynamic}` cache; converted the prop loop, identity props, custom_attrs, the
import gate, `build_imports_dict`, `read_tag`, `import_alias_for`. On the Python side,
`_finalize_fields` installs **scalar defaults as plain class attributes** (descriptor
kept only for factory / no-default / descriptor-valued defaults) — `ComponentField.__get__`
invocations fell **6,166 → 657 per page**, fixing the descriptor tax for Python-internal
reads (`_get_vars`, `get_ref`, …) that Rust-side probes can't reach.

**Corrected baseline (important).** The earlier "descriptors regressed freeze 5.5 →
14.3 ms" was a measurement artifact: re-measuring the pre-descriptor commit with
TODAY'S wheel gives freeze ≈ 11.9 ms — the 06-08 "5.5 ms" came from an older wheel
attributing less work to the freeze spans. Apples-to-apples (same wheel): descriptors
+ B = 11.5 vs 11.9 ms, plus the evaluate-side win. There was never a 2.6× regression,
and §2's absolute numbers should be read as same-wheel-relative only.

**A — `format_as_emotion` in Rust.** Full structural port for the base `_get_style`
path: pseudo-selector rewriting (incl. exact `to_kebab_case` regex semantics),
responsive lists and `Breakpoints` → `@media` maps (with dict-comprehension key
semantics and `setdefault().update()` merging), raw-subdict passthrough, nested
recursion, insertion order, `breakpoints_values` read live from the mutable global.
Unsupported structures fall back to the Python callback. VarData is deliberately not
reproduced: the rendered output never consumed it on this path (style VarData reaches
hooks/imports via `_get_vars`' synthetic style Var). Gated by the oracle + a 12-case
differential suite (`tests/units/compiler/test_rust_style_emotion.py`) asserting
byte-equality against `LiteralVar.create(format_as_emotion(...))` for breakpoints
(named/custom/dict-valued), colon/multi-word pseudos, raw nested dicts, css vars,
list merges, Vars, and empty nested dicts. Also: the `_get_style` / `_get_imports`
override identity checks are now cached per class.

**Result (complicated page, same wheel):** style slice 4.6 → **3.0 ms**, freeze_total
≈ **11.2 ms**, full **19.2 → ~18.2 ms**. Stage split: **17.7 → 14.72 ms/route** (×1.20
single-thread since program start). Refreshed structural numbers at 17 pages: cache
warm all-hits **27.8×** / 1-edit **9.7×**; warm fork pool **5.4×** at w=12.

**Where the remaining freeze time is (cProfile):** Python execution in the imports
slice — `_get_vars` (~7.5 ms cum/page across hooks+imports callers),
`_get_dependencies_imports` / `_get_hooks_imports`, and the hooks harvests. The next
freeze-side wins are ports of those harvests, not more boundary tuning.

---

## 12. Reproduce

```bash
# Rebuild (release, incremental):
cd packages/reflex-compiler-rust && uv run maturin develop --release

# Byte-parity gate (run capture once as baseline, check after each change):
# (PYTHONHASHSEED pin no longer needed — determinism verified cross-seed;
#  golden lives in-repo at tests/codegen_corpus/parity_golden.json)
uv run python scripts/parity_oracle.py capture
uv run python scripts/parity_oracle.py check

# Top-level + stage split:
uv run python scripts/profile_full_rust_compile.py 8 5
uv run python scripts/benchmark_stages.py synthetic:8 5

# Freeze internals: compile a fixture, read sess._inner.last_phase_timings_ns()
#   keys: freeze_total_ns, freeze_{style,imports,imports_slow,props,structural,hooks,optional,events}_ns,
#         imports_fast_count, imports_slow_count
```

> Note: the freeze timers add ~1% overhead (Instant::now per sub-function per node). Before
> merging, gate them behind a cargo feature or remove them.
