# Legacy Compile Pipeline: What Moves to Rust, What Cannot

Measurement source: `scripts/benchmark_stages.py synthetic:20 3` (20 routes,
~165 nodes/route median, 3 runs) plus a per-walk breakdown of the legacy
mechanical compile.

## Where time goes today

Per-page (median, ms) on the 20-route synthetic app:

| Stage                          | Median  | Mean   | What it does                                                          |
| ------------------------------ | ------- | ------ | --------------------------------------------------------------------- |
| framework                      | 10.65   | 7.42   | Runs user page callable, Var/Component alloc, theme apply, Fragment wrap |
| py_mech (legacy mechanical)    | 11.75   | 12.71  | All `_get_all_*` walks + `render()` + page template                   |
| pyread (existing Rust path)    | 1.86    | 1.85   | PyO3 single-pass walk + IR build + JSX emit                           |

Speedup of mechanical phase, pyread vs py_mech: **6.9×**.
Per-page total today: legacy ~22.4 ms, run-rust ~12.5 ms. **~9.9 ms saved/page
(44%)** already shipping behind `reflex run-rust`.

## Breakdown inside py_mech (where Rust replaces it)

Per-page median, ms — independent timing of each walk:

| Walk                                | Median ms | Notes                                                                        |
| ----------------------------------- | --------- | ---------------------------------------------------------------------------- |
| `render()`                          | 8.94      | Recursive `_render()` → Tag → dict per node + `_replace_prop_names`          |
| `_get_all_imports`                  | 2.68      | Recursive per-node `_get_imports` + import dict merge                        |
| `_get_all_app_wrap_components`      | 0.80      | Per-class `_get_app_wrap_components` + recursive scan                        |
| `memoize predicate walk`            | 0.52      | `_should_memoize` per node (Var reactivity check + MRO)                      |
| `_get_all_hooks_internal`           | 0.24      | Mostly per-node; small                                                       |
| `_get_all_hooks`                    | 0.15      | User hooks + added hooks (MRO walk per node)                                 |
| `page_template` (Jinja)             | 0.11      | Final string format                                                          |
| `_get_all_custom_code`              | 0.08      | Per-class `_get_custom_code` + `add_custom_code` MRO                         |
| `_get_all_dynamic_imports`          | 0.06      | Per-class override                                                           |
| Total py_mech                       | ~13.6     |                                                                              |

`render()` alone is **66% of py_mech**. Killing it via a Rust JSX emit over an
arena is the single biggest lever.

## Two categories of work in the legacy pipeline

1. **Tree walks + aggregation** — visit every node, collect/merge per-node
   data, run a predicate, or emit a string. These are *side-effect free*,
   bound by Python interpreter overhead, and benefit ~10× from a Rust arena
   walk. **These move to Rust.**
2. **Per-Component leaf methods** — `_get_imports`, `_get_custom_code`,
   `_get_hooks`, `_get_added_hooks`, `_get_app_wrap_components`,
   `_get_style`, `_get_vars`, `_render`, and the Var system. These read
   user-overridable Python methods or evaluate `Var` operator-overloaded
   expressions, so they **must run in Python during freeze**. After freeze
   they never run again.

The split is therefore: **freeze pass calls every per-Component method once
and packs the result into the arena. Every walk after that is pure Rust.**

## Function-by-function inventory

### Walks that move to Rust (operate on the arena, no Python callbacks)

Each is a bottom-up arena traversal over already-frozen per-node data. Time
column is the projected ms/page (~165 nodes) based on the existing pyread's
1.86 ms total budget.

| Legacy function                       | Per-node data needed in IR                                     | Projected ms/page |
| ------------------------------------- | -------------------------------------------------------------- | ----------------- |
| `Component.render()`                  | `tag`, `rendered_props[]`, `event_callbacks[]`, `children`, `ref_name`, `style` (rendered) | 0.5 |
| `_get_all_imports`                    | `imports[]` (per-node SmallVec of (lib, ImportEntry))          | 0.2               |
| `_get_all_hooks_internal`             | `hooks_internal[]` (per-node)                                  | 0.05              |
| `_get_all_hooks`                      | `hooks_user[]` (per-node, includes user_hook + added_hooks)    | 0.05              |
| `_get_all_custom_code`                | `custom_code` (Option\<Symbol\>) + add_custom_code expansion baked in | 0.02       |
| `_get_all_dynamic_imports`            | `dynamic_imports[]`                                            | 0.02              |
| `_get_all_app_wrap_components`        | `app_wrap_components[]` (arena indices)                        | 0.1               |
| `_get_all_refs`                       | `ref_name` (Option\<Symbol\>)                                  | 0.02              |
| `_get_component_hash` / subtree hash  | `flags`, child hashes — computed bottom-up at freeze close     | 0.05              |
| `compile_imports` (sort/dedupe)       | merged ImportMap                                               | 0.05              |
| `walk_and_memoize` rewrite            | `flags` (has_state_or_hooks, has_event_triggers, mem_disposition), `vars_used[]` | 0.1     |
| `_should_memoize` predicate           | `flags` (per-node precomputed at freeze)                       | 0.02              |
| `_subtree_has_reactive_data`          | `flags.propagates_hooks` (computed bottom-up at freeze)        | 0                 |
| `fix_event_triggers_for_memo`         | `event_callbacks[]` — rewrite in place                         | 0.05              |
| `_add_style_recursive` merge          | `style` (per-node) merged with App.style table by class key    | 0.1               |
| `format_as_emotion` style→JS          | `style` keys/values (symbols)                                  | 0.05              |
| `_render_hooks` template format       | merged hook list                                               | 0.02              |
| `page_template` (Jinja)               | already in Rust codegen crate                                  | already in Rust   |

**Projected aggregate cost after freeze: ~1.4 ms/page** of pure-Rust walk
work — comparable to the existing pyread which already does most of these
inline, but cleanly factored into reusable passes over the arena.

### Per-Component methods called ONCE during freeze (stay in Python)

Each is called once per Component instance. The result is read into the
arena and never re-evaluated.

| Method                              | Data extracted to IR field        | Why it must stay Python                                       |
| ----------------------------------- | --------------------------------- | ------------------------------------------------------------- |
| `library`, `tag`, `alias`           | `tag: Symbol`                     | Class attributes — field reads                                |
| `_get_imports()`                    | `imports[]`                       | Calls user `add_imports` MRO + `_get_hooks_imports` + Var data |
| `_get_vars()`                       | `vars_used[]`, `event_callbacks[]`| Iterates props + extracts Var refs (operator-overloaded)      |
| `_get_hooks_internal()`             | `hooks_internal[]`                | Calls `_get_ref_hook`, `_get_mount_lifecycle_hook`, var hooks |
| `_get_hooks()`                      | part of `hooks_user[]`            | User override returning a Var (renders to JS via Var.__str__) |
| `_get_added_hooks()`                | part of `hooks_user[]`            | MRO walk over user `add_hooks` classmethods                   |
| `_get_custom_code()` + MRO          | `custom_code`                     | User overrides + `add_custom_code` MRO                        |
| `_get_dynamic_imports()`            | `dynamic_imports[]`               | User override                                                 |
| `_get_app_wrap_components()`        | `app_wrap_components[]`           | User override + recursive resolution                          |
| `_get_style()` → `format_as_emotion`| `style` (rendered as JS expr)     | `Style` is a Python class with Var-aware merge semantics      |
| `_render()` (props pack)            | `rendered_props[]`                | Builds prop dict from `get_props()` + key/id/class_name       |
| `get_props()` (classmethod, cached) | feeds prop iteration              | Dataclass field discovery — pure Python class introspection   |
| Var: `_get_all_var_data()`          | per-Value: state/hooks/imports/components | Recursive VarData merge through Var operator tree     |
| Var: `_js_expr`                     | `Value::JsExpr.expr`              | The rendered JS string — Var system property                  |
| `Foreach._render()` →`render_component(arg)` | body subtree                | Creates typed iter-var for body (Var type inference)          |
| `LiteralVar.create(spec)` (events)  | event callback JS                 | EventChain → JS rendering (uses Var infra)                    |
| `_get_components_in_props()`        | traversal cue for prop-trees      | Detects nested Components in Var props (cached property)      |
| `_iter_parent_classes_with_method`  | drives MRO walks                  | Python class hierarchy introspection                          |

All of these have one thing in common: they depend on `Var` or class MRO,
which is Reflex's user-facing API. Porting any of them would mean porting
the Var operator-overloading system to Rust — a strictly larger project
than the compile pipeline itself.

### Functions that stay in Python but don't run during pipeline hot path

- `compile_unevaluated_page` — runs user page callable, applies theme/style,
  wraps in Fragment + title/meta. Counted as `framework` (10.65 ms).
- `_add_style_recursive` — recursive style apply. Can be moved post-freeze
  (style merging on the arena) so it never enters the hot path.
- Plugin `pre_compile` hooks (Tailwind, etc.) — config-time, called once.
- `_resolve_root_stylesheets` — filesystem + SASS, side effects required.

## Projected time savings

Per page (~165 nodes), median:

| Phase                     | Today (py_mech) | After full Rust walks | Saved   |
| ------------------------- | --------------- | --------------------- | ------- |
| render JSX emit           | 8.94 ms         | 0.5 ms                | 8.44 ms |
| imports/hooks/code merge  | 3.21 ms         | 0.4 ms                | 2.81 ms |
| memoize predicate + walk  | 0.52 ms         | 0.07 ms               | 0.45 ms |
| app_wrap collect          | 0.80 ms         | 0.1 ms                | 0.7 ms  |
| page_template format      | 0.11 ms         | 0.02 ms               | 0.09 ms |
| **mechanical total**      | **~13.6 ms**    | **~1.1 ms**           | **~12.5 ms** |

Plus the freeze pass cost (~0.7–1.0 ms/page, similar to pyread's per-node
boundary cost today). **Net: ~11.5 ms saved per page** vs legacy pipeline
once full Rust walks land, or ~1 ms saved per page vs today's pyread (the
remaining win is incremental — see below).

For a 50-page app:
- Cold compile: **~575 ms saved** (from ~1.5 s to ~0.9 s mechanical work).
- Hot reload with arena cache: changed pages re-freeze (~1 ms each), every
  cached subtree reuses its Rust arena. A single-component change touches
  <1% of nodes — compile cost becomes **linear in the diff, not in the app
  size**. This is the qualitative shift the plan is really after.

## How freeze stays zero-overhead

The freeze pass produces the arena. For it not to be the new bottleneck,
five constraints apply:

1. **One PyO3 boundary crossing per Component**, not per field. Freeze
   calls `arena.append_node(component)` and Rust reads every field
   internally — same model the existing pyread uses (`pyo3_reader.rs`
   harvests tag, props, events, var_data, refs, imports in one
   `read_element` call).
2. **No callbacks Rust→Python during walks.** Per-Component methods
   (`_get_imports`, `_get_hooks_internal`, etc.) are called by the Rust
   side, but only as one-shot Python invocations whose result is *copied*
   into the arena. After freeze closes, no Rust code calls back into
   Python.
3. **Single pass.** Today the legacy pipeline does 5+ `_get_all_*`
   walks plus a `render()` walk plus a memoize-decision walk. Freeze
   replaces all of them with one bottom-up traversal. Each
   `_get_imports`/`_get_hooks_internal`/`_get_custom_code` runs exactly
   once per node instead of being called by each `_get_all_*` recursion.
4. **Observation-only.** Freeze never mutates a Component. Style merge,
   event-trigger rewriting, and memoize wrapper insertion all happen as
   *separate transform passes* over the arena — they're cheap arena ops,
   not Python tree rewrites. An `REFLEX_DEBUG_FREEZE=1` assert catches
   accidental mutations.
5. **No serialization.** Arena lives in Rust. Python passes the Component
   handle directly through PyO3; Rust reads, interns strings, packs
   into `Vec<NodeSnapshot>`. No msgpack/bincode/dict-of-dicts step in
   between. Memory ownership is Rust-side throughout the compile.

The bottom-up walk also computes the per-subtree hash and the bit-packed
`flags` (has_state_or_hooks, has_event_triggers, propagates_hooks,
memoization_disposition) at freeze close — this is what makes the
downstream memoize predicate a single bit-test instead of a per-node
Python predicate.

## Single concrete recommendation, given the data

`render()` is 66% of mechanical work. The plan's Phase 3 starts with
imports (~3 ms/page payoff). The data here says **moving render
to a Rust arena emit is the biggest single win** (~8.5 ms/page) and should
be considered for an earlier phase. Imports work as the *validation* gate
(well-bounded I/O, easy diff) but the structural payoff lives in render.
