# Rust Port Inventory

Each entry: the legacy Python function we're porting, where it lives, and
the IR fields the Rust replacement needs to read or write. No
implementation plan — this is the data contract the freeze pass has to
satisfy.

Convention: `Symbol = u32` (interned string), `NodeId = u32` (arena
index), `SmallVec<[T; N]>` for short inline-allocated lists,
`Range<u32>` for child index spans into the flat arena.

---

## 1. `Component.render()`

**Location:** `packages/reflex-base/src/reflex_base/components/component.py:1400`
**Today's cost:** 8.94 ms/page median — single biggest lever (66% of py_mech).
**Replaces:** recursive `_render()` → `Tag` → dict, then `_replace_prop_names`, then `templates._render_jsx` format pass.

### IR fields needed per node

| Field                | Type                                   | Filled by                                             |
| -------------------- | -------------------------------------- | ----------------------------------------------------- |
| `kind`               | `NodeKind` (Tag/Bare/Cond/Foreach/Match/Fragment/Text) | freeze, from class dispatch                 |
| `tag`                | `Option<Symbol>`                       | `component.tag` / `alias` / `_is_tag_in_global_scope` |
| `rendered_props`     | `SmallVec<[(Symbol, Symbol); 4]>` — `(prop_name → rendered JS expr)` | freeze: `_render()` packs props, each value rendered via `Var.__str__` |
| `event_callbacks`    | `SmallVec<[(Symbol, Symbol); 2]>` — `(trigger_name → JS expr)` | freeze: walks `event_triggers`, calls `LiteralVar.create()` to render |
| `style`              | `Symbol` (rendered emotion JSX string) | freeze: `_get_style()` runs `format_as_emotion(self.style)` once |
| `ref_name`           | `Option<Symbol>`                       | `component.get_ref()` (depends on `self.id`)          |
| `key`, `id`, `class_name` | folded into `rendered_props`      | same packing as `_render`                              |
| `custom_attrs`       | folded into `rendered_props`           | same                                                   |
| `children`           | `Range<u32>` (arena indices)           | freeze, depth-first append order                       |
| `special_props`      | `SmallVec<[Symbol; 1]>`                | `component.special_props` (Var → JS expr)              |
| `_rename_props`      | `SmallVec<[(Symbol, Symbol); 0]>`      | per-class, applied at emit time                        |

Rust emit walk: arena traversal → JSX string via `reflex_codegen` (already exists).

---

## 2. `_get_all_imports`

**Location:** `packages/reflex-base/src/reflex_base/components/component.py:1901`
**Today's cost:** 2.68 ms/page.
**Replaces:** recursive `_get_imports()` aggregation + `merge_parsed_imports` + optional `collapse_imports`.

### IR fields needed per node

| Field              | Type                              | Filled by                                            |
| ------------------ | --------------------------------- | ---------------------------------------------------- |
| `imports`          | `SmallVec<[ImportEntry; 4]>` where `ImportEntry { lib: Symbol, tag: Option<Symbol>, render: bool, alias: Option<Symbol>, install: bool, transpile: bool }` | freeze: `_get_imports()` once (cached via `_imports_cache`) |

`_get_imports()` itself merges:
- `_get_dependencies_imports()` — `lib_dependencies` field, no rendering
- `_get_hooks_imports()` — pulls imports from `useRef`, `useEffect`, user-hook VarData
- `{library: [import_var]}` if both set
- `event_triggers` → static `Imports.EVENTS` if any triggers present
- per-Var: `var._get_all_var_data().imports`
- per-class `add_imports` MRO calls (parsed via `imports.parse_imports`)

Rust walk: bottom-up concatenate all per-node `imports[]`, then dedupe by `(lib, tag, render)` keyed map.

---

## 3. `_get_all_hooks_internal` + `_get_all_hooks`

**Location:** `component.py:2057` and `:2072`
**Today's cost:** 0.39 ms/page combined.
**Replaces:** recursive aggregation of internal hooks (events/ref/mount/var) + user hooks + added hooks.

### IR fields needed per node

| Field             | Type                                | Filled by                                                |
| ----------------- | ----------------------------------- | -------------------------------------------------------- |
| `hooks_internal`  | `SmallVec<[HookEntry; 2]>` where `HookEntry { code: Symbol, position: HookPosition, var_data_ref: u32 }` | freeze: `_get_hooks_internal()` once (cached) |
| `hooks_user`      | `SmallVec<[HookEntry; 1]>`          | freeze: `_get_hooks()` + `_get_added_hooks()` once       |

`_get_hooks_internal` is built from:
- `_get_events_hooks` — `Hooks.EVENTS` if `event_triggers`
- `_get_ref_hook` — depends on `self.id` (non-Var, non-None)
- `_get_mount_lifecycle_hook` — depends on `on_mount`/`on_unmount` triggers
- `_get_vars_hooks` — every Var.var_data.hooks plus components inside var_data

Rust walk: position-aware ordered merge (preserves `HookPosition.INTERNAL`-then-user ordering used by `_render_hooks`).

---

## 4. `_get_all_custom_code`

**Location:** `component.py:1746`
**Today's cost:** 0.08 ms/page.
**Replaces:** recursive `_get_custom_code()` + `add_custom_code` MRO walk + dedup.

### IR fields needed per node

| Field              | Type                  | Filled by                                                     |
| ------------------ | --------------------- | ------------------------------------------------------------- |
| `custom_code`      | `Option<Symbol>`      | freeze: `_get_custom_code()` once                             |
| `add_custom_code`  | `SmallVec<[Symbol; 0]>` | freeze: `_iter_parent_classes_with_method("add_custom_code")` expanded once |

Rust walk: bottom-up insertion-ordered dict (preserves legacy emit order).

---

## 5. `_get_all_dynamic_imports`

**Location:** `component.py:1783`
**Today's cost:** 0.06 ms/page.

### IR fields needed per node

| Field              | Type             | Filled by                          |
| ------------------ | ---------------- | ---------------------------------- |
| `dynamic_imports`  | `SmallVec<[Symbol; 1]>` | freeze: `_get_dynamic_imports()` once |

Rust walk: bottom-up set union.

---

## 6. `_get_all_app_wrap_components`

**Location:** `component.py:2145`
**Today's cost:** 0.80 ms/page.
**Replaces:** recursive collection of `_get_app_wrap_components()` results into `dict[(int, str), Component]`, walking both children and nested wrappers, with id-based dedupe.

### IR fields needed per node

| Field                  | Type                                       | Filled by                                                 |
| ---------------------- | ------------------------------------------ | --------------------------------------------------------- |
| `app_wrap_components`  | `SmallVec<[(i32, Symbol, NodeId); 0]>` — `(sort_key, name, root_arena_idx)` | freeze: `_get_app_wrap_components()` once, plus each wrapper's subtree appended to the arena |

Note: wrapper subtrees need their own arena nodes (they get rendered as JSX too). Freeze must walk wrappers recursively and emit their nodes alongside the main tree.

Rust walk: bottom-up dedupe by `(sort_key, name)` key, preserving first-seen `NodeId`.

---

## 7. `_get_all_refs`

**Location:** `component.py:2107`
**Today's cost:** rolled into `render()` today; small.

### IR fields needed per node

| Field      | Type             | Filled by                          |
| ---------- | ---------------- | ---------------------------------- |
| `ref_name` | `Option<Symbol>` | `component.get_ref()` (same field used for render) |

Rust walk: bottom-up dict insertion.

---

## 8. `_get_component_hash` / subtree hashing

**Location:** `component.py:1420`
**Today's cost:** only paid during memoize tag generation; not in py_mech baseline. Required for Phase 8 hot-reload cache.

### IR fields needed per node

| Field           | Type | Filled by                                                                              |
| --------------- | ---- | -------------------------------------------------------------------------------------- |
| `subtree_hash`  | `u64` | freeze close: bottom-up `xxhash64(kind, tag, rendered_props, style, event_callbacks, hooks_*, custom_code, children's subtree_hash...)` |

No Python callbacks. Hash is the cache key for incremental compilation.

---

## 9. `_should_memoize` predicate + `_subtree_has_reactive_data`

**Location:** `reflex/compiler/plugins/memoize.py:120` and `:40`
**Today's cost:** 0.52 ms/page combined.
**Replaces:** per-node predicate that walks Var.var_data + children to decide memoization.

### IR fields needed per node (already covered above plus)

| Field   | Type        | Bits                                                                                      |
| ------- | ----------- | ----------------------------------------------------------------------------------------- |
| `flags` | `NodeFlags` | `has_state_or_hooks: 1`, `has_event_triggers: 1`, `is_bare: 1`, `is_snapshot_boundary: 1`, `propagates_hooks: 1`, `memoization_disposition: 2` (NEVER/ALWAYS/AUTO), `is_structural_memo_child: 1`, `tag_is_none: 1` |

Each bit is filled at freeze time from the corresponding Python predicate:
- `has_state_or_hooks` ← any `var_data.state` or `var_data.hooks` in `_get_vars`, or `_get_hooks_internal()` non-empty modulo the ref hook, or `_get_hooks()` not None, or `_get_added_hooks()` non-empty
- `has_event_triggers` ← `bool(event_triggers)`
- `is_bare` ← `isinstance(self, Bare)`
- `is_snapshot_boundary` ← `is_snapshot_boundary(self)` (per-class)
- `propagates_hooks` ← bottom-up: any descendant `has_state_or_hooks` (computed at freeze close, not at the leaf)
- `memoization_disposition` ← `self._memoization_mode.disposition`
- `is_structural_memo_child` ← `_is_structural_memoization_child(self)` (per-class)

After freeze, `_should_memoize` is a single bit-test in Rust. `_subtree_has_reactive_data` is `flags.propagates_hooks` — already precomputed.

---

## 10. `walk_and_memoize` tree rewrite

**Location:** `reflex/compiler/rust_memo.py:51` (and legacy plugin in `plugins/memoize.py`)
**Today's cost:** runs as part of the page walk; included in `should_memoize` budget.
**Replaces:** Python recursive walk that wraps memoizable subtrees in `Passthrough` wrappers and registers memo bodies.

### IR fields needed

Arena adds a new node kind:

```
NodeKind::MemoizeWrapper {
    body_id: u32,         // index into MemoizeBody table
    wrapper_tag: Symbol,  // generated export name
    children: Range<u32>, // page-level children (passthrough)
}
```

Plus a separate `MemoizeBody` table on the arena:

```
struct MemoizeBody {
    export_name: Symbol,
    signature: Symbol,       // "({ children })" or "()"
    body_root: NodeId,       // root of the captured subtree in the arena
    pre_hooks: SmallVec<[HookEntry; 2]>,
    hash: u64,
}
```

Rust walk: bottom-up, for each node test `flags`. If memoization triggers, allocate a `MemoizeWrapper` node and clone-or-reference the original subtree as the memo body. Body dedup keyed on `subtree_hash`.

No Python callbacks. `create_passthrough_component_memo` (which today allocates Python Component classes for each unique memo) is replaced by IR-level body registration — Python only needs to be called at freeze for the `export_name` formatting which can also be a pure Rust string format on `subtree_hash`.

---

## 11. `fix_event_triggers_for_memo`

**Location:** `packages/reflex-base/src/reflex_base/components/memoize_helpers.py:151`
**Today's cost:** rolled into memoize walk.
**Replaces:** rewrites `comp.event_triggers` into `useCallback`-wrapped JS forms for the memo body.

### IR fields needed

| Field             | Type                                | Operation                                                  |
| ----------------- | ----------------------------------- | ---------------------------------------------------------- |
| `event_callbacks` | `SmallVec<[(Symbol, Symbol); 2]>`   | rewrite in place: wrap each rendered JS expr in `useCallback(...)` with deps derived from `vars_used[]` |
| `vars_used`       | `SmallVec<[VarDataRef; 4]>` (already in IR) | provides callback deps                              |

Pure arena mutation. No callback to Python.

---

## 12. `_add_style_recursive` (App.style merge)

**Location:** `component.py:1333`
**Today's cost:** runs in `compile_unevaluated_page` (framework phase) today.
**Replaces:** recursive walk merging `App.style[component_class]` into each node's `style`.

### IR fields needed

| Field        | Type                              | Operation                                                                          |
| ------------ | --------------------------------- | ---------------------------------------------------------------------------------- |
| `style_keys` | per-node `Symbol` — the Python class qualname (already-resolved style lookup key) | freeze: `type(self).__qualname__` once |
| `style`      | `Symbol` (rendered emotion JS)    | merged form                                                                        |

Plus a side table: `app_style_map: HashMap<Symbol, Style>` passed once at compile start.

Rust walk: iterate arena, for each node look up `app_style_map[style_keys]`, merge with per-node style (overwrite order: defaults → app style → instance style), emit rendered emotion JS.

Caveat: `format_as_emotion` must also be reimplemented in Rust — it walks the style dict and emits emotion JSX syntax. The keys are simple (camel-cased CSS), so this is a string-format pass.

---

## 13. `format_as_emotion`

**Location:** `packages/reflex-base/src/reflex_base/style.py` (via `_get_style`)
**Today's cost:** rolled into render().
**Replaces:** Python emotion-CSS dict → JS object expression.

### IR fields needed

Operates on the `style` field above. Pure string format — no Python needed once the style dict has been frozen into `(key: Symbol, value: Symbol)` pairs in the arena.

---

## 14. `_render_hooks` (templates)

**Location:** `packages/reflex-base/src/reflex_base/compiler/templates.py`
**Today's cost:** 0.12 ms/page (page_template includes this).
**Replaces:** Jinja-style hook block format that orders hooks by `HookPosition` and concatenates.

### IR fields needed

| Field            | Type            | Operation                                       |
| ---------------- | --------------- | ----------------------------------------------- |
| merged hook list | from walks 3    | sort by `position`, join with `\n`              |

Pure Rust string assembly. Already partially in `reflex_codegen`.

---

## 15. `compile_imports` (sort + dedupe + format)

**Location:** `reflex/compiler/utils.py`
**Today's cost:** ~0.1 ms/page (rolled into import walk).
**Replaces:** Python sort+dedup of `ParsedImportDict` → `[CompiledImport]`.

### IR fields needed

Operates on the output of walk 2. Pure Rust map sort, no per-Component data needed beyond the merged ImportMap.

---

## 16. `page_template` (Jinja)

**Location:** `reflex/compiler/templates.py`
**Today's cost:** 0.11 ms/page.
**Status:** already in Rust via `reflex_codegen` (page template format exists). Schema needs to consume the arena directly instead of intermediate dicts.

---

# IR Schema Summary

Aggregating the fields above, every `NodeSnapshot` in the arena needs:

```rust
struct NodeSnapshot {
    kind: NodeKind,                                          // 1 byte (enum)
    tag: Option<Symbol>,                                     // 4 bytes
    style_key: Symbol,                                       // 4 bytes — class qualname for App.style lookup
    style: Symbol,                                           // 4 bytes — rendered emotion JS
    rendered_props: SmallVec<[(Symbol, Symbol); 4]>,         // walk 1
    event_callbacks: SmallVec<[(Symbol, Symbol); 2]>,        // walk 1 + 11
    imports: SmallVec<[ImportEntry; 4]>,                     // walk 2
    hooks_internal: SmallVec<[HookEntry; 2]>,                // walk 3
    hooks_user: SmallVec<[HookEntry; 1]>,                    // walk 3
    custom_code: Option<Symbol>,                             // walk 4
    add_custom_code_extra: SmallVec<[Symbol; 0]>,            // walk 4
    dynamic_imports: SmallVec<[Symbol; 1]>,                  // walk 5
    app_wrap_components: SmallVec<[(i32, Symbol, NodeId); 0]>, // walk 6
    ref_name: Option<Symbol>,                                // walk 7
    vars_used: SmallVec<[VarDataRef; 4]>,                    // walk 11 (callback deps)
    special_props: SmallVec<[Symbol; 1]>,                    // walk 1
    rename_props: SmallVec<[(Symbol, Symbol); 0]>,           // walk 1
    children: Range<u32>,                                    // 8 bytes
    flags: NodeFlags,                                        // 2 bytes (bit-packed, walk 9)
    subtree_hash: u64,                                       // 8 bytes (walk 8, computed at freeze close)
}
```

Side tables:
- `StringInterner` (Symbol → &str), per compile.
- `MemoizeBody` table (walk 10).
- `app_style_map: HashMap<Symbol, Style>` (walk 12, populated once at compile start).
- `VarData` side table (VarDataRef → state/hooks/imports/components-info needed by walks 2/3/11).

# What freeze does

Single bottom-up Python walk over the Component tree. For each Component:

1. Allocate `NodeSnapshot` index `i` in the arena.
2. Read class dispatch → `kind`.
3. Call each per-Component method **once**: `_get_imports`, `_get_hooks_internal`, `_get_hooks`, `_get_added_hooks`, `_get_custom_code`, `_get_dynamic_imports`, `_get_app_wrap_components`, `_get_style` → `format_as_emotion`, `_render` (for prop pack), `get_ref`, `event_triggers` iteration with `LiteralVar.create` for non-Var handlers.
4. For each Var encountered: `var._get_all_var_data()` once, store as `VarDataRef`.
5. Recurse into `children`. Their indices fill `children: Range<u32>`.
6. Compute `flags` from local data; `propagates_hooks` waits until children are done.
7. At close: bottom-up pass over the arena computes `subtree_hash` and `propagates_hooks`.

After freeze closes, **no Python is invoked** until the next compile.
