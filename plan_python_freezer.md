# Python freezer plan — one user walk, post-order recording, frame-stacked

## Why this plan exists

Today's compile path crosses the PyO3 boundary **961 times per page** (measured). The work inside each callback is cheap, but cumulative boundary tax is ~17 ms/page.

Goal: **PyO3 boundary calls during compile = 1 per page.** Everything else either happens inside the user's `def page()` execution (Python, no boundary) or after the bytes are inside Rust (pure Rust, GIL released).

---

## Critical safety invariants (review-driven)

Earlier drafts of this plan glossed over four traps. They are the *first-class* design contract; everything else is a fill-in.

### Invariant 1 — Recording is reentrant, suspendable, and stack-scoped

`Component._post_init` records into the **top frame** of a recording stack — *not* a bare module global. Schema probes, helper Component construction, custom-component renders nested inside a freeze, and any future parallel-route compile must each be able to:

- Push a fresh frame (nested compile)
- Push a *suspended* sentinel that swallows recordings (schema probes, defaults)
- Pop on exit, even on exception

Any code that needs to construct a `Component` for inspection (schema probing, default-instance synthesis, helpers) **must** run inside `with freezer.suspended():` (or, better, avoid constructing components entirely — see Invariant 4).

### Invariant 2 — Python construction is post-order; Rust still wants pre-order

Python evaluates constructor args before the constructor body, so children record before parents:

```
rx.box(rx.text("a"), rx.text("b"))
    rx.text("a") → records as node 0
    rx.text("b") → records as node 1
    rx.box(...)  → records as node 2  ← parent at the HIGH index
```

Today's `reflex_ir::Snapshot` assumes **parent-before-children** (NodeIdx of any child > NodeIdx of its parent). The backward subtree-hash close pass, the emit walks, the memoize wrapper insertion — all rely on it.

**A remap pass runs at the wire boundary** (Rust side, inside `build_snapshot`). Post-order Python indices → pre-order Rust indices. One linear DFS from `root`, rewrites every NodeIdx reference. After remap the Snapshot looks exactly like today's. Cost: O(N), ~5 µs for a 150-node page.

`Snapshot.child_lists` (the side-table) is **necessary but not sufficient** — it removes the contiguous-children invariant but does not fix child-before-parent ordering. Both changes are needed.

### Invariant 3 — Control-flow components materialize children lazily

`rx.cond`, `rx.foreach`, `rx.match`, custom `@rx.memo` components, and any user wrapper factory can construct child Components **inside their own `_post_init`** or via a deferred callable (e.g. `Foreach`'s `render_fn(item)`). Naïvely waiting for "all constructors to finish" leaves these subtrees unrecorded.

The freezer dispatches per-kind during `_record_self`:

| Kind | Strategy |
|---|---|
| Element / Fragment / Bare-with-literal | already recorded by their normal `_post_init` order |
| `Cond` | both branches are already-constructed `Component` args; their `_post_init` already fired. Just record the test expression in `_COND_TEST` |
| `Foreach` | invoke `render_fn(iter_var._var_index_placeholder)` eagerly during `_record_self`; the resulting body Component's own `_post_init` records into the current frame |
| `Match` | each arm body is already-constructed (arg evaluation). Record arm pairs `(case_expr, body._arena_idx)` into `_MATCH_ARMS` |
| Custom `@rx.memo` body | the wrapper's `_post_init` invokes the user fn, body construction records via the same mechanism |

The full list of Component variants that need a `_record_self` per-kind branch lives in §"Per-kind dispatch table" below — it is part of Phase 2's scope, not an after-thought.

### Invariant 4 — Class schemas are derived without instantiating probes

Building a `_ClassSchema` by constructing two probe instances (the earlier "probe-and-compare" idea) is unsound: any probe construction inside an active freeze would pollute the arena (Invariant 1) and the comparison only catches a narrow class of non-determinism. **Default classification uses class-level introspection only**:

| Detection | How |
|---|---|
| `has_add_imports_override` | `"add_imports" in cls.__dict__` for any class in the MRO above `Component` |
| `has_get_hooks_internal_override` | same pattern |
| `has_get_style_override` | same pattern |
| `has_property_overrides` | scan `cls.__dict__` for `property` instances on declared prop field names |
| `has_getattribute_override` | `"__getattribute__" in cls.__dict__` for the class chain |
| `tag`, `library`, `lib_dependencies` | read as class attributes — no instance needed |
| `prop_names` | `cls.get_props()` is already a classmethod returning class-level info — call once, cache |

If `has_add_imports_override` is `False`, the import dict is **derivable from class metadata alone** (just `{cls.library: [ImportVar(...)]}`). Cache the pre-rendered tuple.

If any override is present, classify the class as **per-instance**: `_record_self` calls the override on the live instance, no probe needed. Slower but correct.

Probe construction (wrapped in `suspended()`) is only ever a future, opt-in optimization for the override case — never the default path.

---

## Architecture

```
user page() runs in Python (one walk: the user's own def page() body)
   constructors fire in post-order
        │ each Component._post_init reads `_FRAME` (ContextVar) and,
        │ if a non-suspended frame is active, appends its record to
        │ that frame's lists.
        ▼
Active frame is FULL in post-order:
   nodes:        [text_a, text_b, box]
   var_data:     [...]
   child_lists:  [0, 1]
   control_flow: {...}
   ...           root_idx = 2  (the LAST-pushed node)
        │
        ▼
Append Fragment + title/meta wrapper as 1-3 extra _record_self pushes
   (same active frame — no separate walk)
        │
        ▼
sess.compile_from_arena(*frame.lists_and_dicts, root_idx, route, ...)
   ── ONE PyO3 call, bulk-extract args at the function boundary
        │
        ▼
Rust:
   1. remap post-order indices → pre-order (single DFS from root)
   2. assemble reflex_ir::Snapshot (existing invariants restored)
   3. close_with_hashes()  (backward walk computes subtree_hash)
   4. memoize_arena_pass
   5. emit page + memo body modules
   6. write_if_changed
   ── pure Rust, GIL released for steps 2-6
```

Walks of the user's component definition: **1** (the constructor execution itself).
Post-construction tree walks of `Component` instances: **0**.
PyO3 calls during compile: **1**.

---

## State during construction — `ContextVar` frame (parallel- and async-safe)

A module-global stack would break the moment a parallel route compile, an `asyncio` task, or a thread-pool worker pushes its own frame; the global is shared across all of them. **`ContextVar` is the right primitive from day one** — each compile pushes/pops its own context, and Python's contextvars semantics give us free thread-locality + async-task-locality + nested same-thread reentrance.

```python
# reflex/compiler/freeze.py
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

@dataclass(slots=True)
class _Frame:
    """One in-flight compile's accumulators. Post-order during construction."""
    nodes:         list = field(default_factory=list)
    var_data:      list = field(default_factory=list)
    var_dedup:     dict = field(default_factory=dict)
    child_lists:   list = field(default_factory=list)
    text_value:    dict = field(default_factory=dict)
    cond_test:     dict = field(default_factory=dict)
    foreach_iter:  dict = field(default_factory=dict)
    match_value:   dict = field(default_factory=dict)
    match_arms:    dict = field(default_factory=dict)
    match_default: dict = field(default_factory=dict)
    expr_value:    dict = field(default_factory=dict)
    memo_key:      dict = field(default_factory=dict)
    app_wraps:     list = field(default_factory=list)
    special_props: dict = field(default_factory=dict)
    rename_props:  dict = field(default_factory=dict)
    theme:         Optional[object] = None
    suspended:     bool = False

# None = no active recording. ContextVar means each thread / asyncio task
# / future parallel-route worker sees its own value.
_FRAME: ContextVar[Optional[_Frame]] = ContextVar("_reflex_freeze_frame", default=None)

def _active() -> _Frame | None:
    """The frame to record into, or None if outside compile / suspended."""
    f = _FRAME.get()
    return None if f is None or f.suspended else f

@contextmanager
def _recording(theme):
    """Open a fresh recording frame. Nested calls push a new frame and
    restore the previous one on exit."""
    frame = _Frame(theme=theme)
    token = _FRAME.set(frame)
    try:
        yield frame
    finally:
        _FRAME.reset(token)

@contextmanager
def suspended():
    """Public API. Code that constructs Components for inspection (schema
    probes, defaults, helpers) wraps the construction in this guard so
    the recordings are dropped."""
    frame = _Frame(suspended=True)
    token = _FRAME.set(frame)
    try:
        yield
    finally:
        _FRAME.reset(token)

# Per-class metadata cache: keyed by type, lives across compiles. Plain
# dict is fine because schema build is pure-functional from `cls`.
_CLASS_SCHEMA: dict[type, "_ClassSchema"] = {}
```

**Cost of `_active()` is measured, not asserted.** Phase 2 includes a microbench that constructs N Components outside any active recording (the common case for normal Reflex apps at runtime) and reports added ns/construction vs unpatched. The ship gate writes the actual µs/M-constructions number into this plan. Hand-waving "~50 ns" is not enough.

Reentrancy properties (free from `ContextVar`):
- **Nested same-thread compile**: `_recording()` pushes a new frame token; `reset(token)` on exit restores the outer frame.
- **Parallel route compile** (future): each worker thread / asyncio task has its own ContextVar value. No coordination needed; no global to clobber.
- **Schema probes**: `with suspended():` activates a sentinel frame; recordings during probe construction discard.
- **Custom-component render mid-freeze**: the body construction runs in the *same* frame (no new `_recording()`), so its records become children of the wrapper, not a separate compile.

---

## Component-side hook (the one change in `reflex_base.Component`)

```python
class Component(BaseModel):
    _arena_idx: int = PrivateAttr(default=-1)

    def _post_init(self):
        # ... existing _post_init body (Pydantic init, validation) ...
        frame = _active()
        if frame is None:
            return                       # outside compile or suspended
        self._arena_idx = _record_self(self, frame)
```

`_record_self(self, frame)`:

1. Look up `_CLASS_SCHEMA[type(self)]`, build via class introspection (Invariant 4) on first sighting. **Never constructs a probe instance.**
2. Read instance fields via `vars(self).get(name)` (no Pydantic descriptor dispatch).
3. For declared field names whose class declares a `@property` override (per the schema flag), fall back to `getattr(self, name)`.
4. Resolve Vars in props/style/events to JS strings inline; dedup via `id(var)` in `frame.var_dedup`.
5. Per-kind dispatch (see table below) for control-flow specifics.
6. Apply theme: `frame.theme.style_for(type(self))` merged with instance `style`.
7. Build `NodeRecord` (NamedTuple, all fields primitive), append to `frame.nodes`, return index.

### Per-kind dispatch table

| `kind` | `_record_self` extras |
|---|---|
| `Element` | rendered props, event callbacks, ref name; standard children range from already-recorded args |
| `Fragment` | children range only |
| `Text` (Bare with literal contents) | `frame.text_value[idx] = literal` |
| `Expr` (Bare with Var contents) | `frame.expr_value[idx] = var_js_string`, add to `vars_used` |
| `Cond` | record `frame.cond_test[idx]`; both branch components are already in args, already recorded |
| `Foreach` | invoke `render_fn` once with a placeholder var that mirrors today's `iter_tag.render_component` shape; the resulting body's constructor runs in the *same* frame and records its subtree; capture `frame.foreach_iter[idx]` |
| `Match` | record `frame.match_value[idx]` and `frame.match_arms[idx] = [(case_js, body._arena_idx), ...]`; default body indexed similarly into `frame.match_default[idx]` |
| `Memoize` (custom `@rx.memo`) | invoke the user fn once inside the same frame, matching today's `CustomComponent.get_component` semantics exactly; record `memo_key` |

Control-flow constructors that don't fit any of these (rare) raise on encounter so failure surfaces during parity testing, not as silent wrong JSX.

### Foreach / CustomComponent parity is a dedicated sub-phase

These two are the riskiest semantic area in the whole port and **must have their own parity gate before the broad `_post_init` hook lands on `Component`**. The Python freezer's invocation of `render_fn` (Foreach) or the user component callable (CustomComponent / `@rx.memo`) must match today's behavior in five places, each pinned by an explicit test:

1. **Timing of invocation** — today `CustomComponent.get_component` runs lazily during render, *after* style application. The freezer must invoke at the equivalent point relative to theme/style merge. Parity test: a custom component that records the order of `self.style` reads + body invocation produces identical sequences both ways.
2. **Style application path** — `_add_style_recursive` walks the tree applying theme styles; the freezer applies them inside `_record_self`. Parity test: a custom component that observes its merged style via a Var-bound prop emits the same JS string both ways.
3. **Placeholder Var shape inside Foreach `render_fn`** — today `iter_tag.render_component` calls `render_fn(item_var)` where `item_var` has a specific name pattern, type, and `_var_data` shape. Parity test: a `render_fn` that introspects the placeholder and emits its `_js_expr` + `_var_state` produces identical JSX both ways.
4. **Error propagation** — if a `render_fn` raises, today the exception propagates with a specific stack frame inside `iter_tag`. The freezer must not silently swallow or wrap in a way that changes the error type or message visible to user code. Parity test: a `render_fn` that raises `ValueError` produces the same exception class + message + (best-effort) frame both ways.
5. **Re-render idempotency** — custom-component bodies that produce different outputs on repeated calls (rare but possible) — the freezer must invoke exactly once per page; today's render path may or may not depending on memoization. Parity test: a custom component with a side-effect counter records invocation count = 1 per page both ways.

Phase 3 cannot ship until tests 1-5 are green on both legacy and Python-freezer paths.

---

## Driver

```python
def evaluate_and_freeze(unev, app_style, app_theme):
    theme = _ThemeCtx(app_style, app_theme)
    with _recording(theme) as frame:
        component = unev.callable(**unev.kwargs)
        # frame is now fully populated.
        root = _append_title_meta_wrapper(frame, component._arena_idx,
                                          unev.title, unev.meta)
    return frame, root          # frame holds all the lists; caller hands them to Rust
```

---

## Record types — NamedTuple in Python, tuple struct in Rust

(Unchanged from previous draft — NamedTuples are tuples at the C level; PyO3 extracts positionally with `PyTuple_GetItem`, no `getattr`.)

```python
# reflex/compiler/_records.py
from typing import NamedTuple

class ImportVarRecord(NamedTuple):
    """Mirrors reflex_base.utils.imports.ImportVar — every field the
    JS emit + `bun install` chain consumes. Collapsing this to (module,
    tag) loses default/named distinction, alias, install-package vs
    JS-specifier disambiguation, and the side-effect-import flag, all
    of which the legacy emit relies on."""
    module:           str             # JS module specifier ("@radix-ui/themes")
    tag:              str | None      # imported binding name; None = side-effect-only import
    alias:            str | None      # local rename, if any
    is_default:       bool            # `import X from "..."` vs `import { X } from "..."`
    install_package:  str | None      # npm package name when it differs from `module`
    render:           bool            # whether to render the import line (False = bun-install only)
    transpile:        bool            # legacy "needs ts→js transpile" flag

class NodeRecord(NamedTuple):
    kind:            int
    tag:             str | None
    library:         str | None
    style:           str | None
    rendered_props:  tuple[tuple[str, str], ...]
    event_callbacks: tuple[tuple[str, str], ...]
    imports:         tuple[ImportVarRecord, ...]              # full shape, not (module, tag)
    hooks_internal:  tuple[tuple[str, int], ...]
    hooks_user:      tuple[tuple[str, int], ...]
    custom_code:     str | None
    dynamic_imports: tuple[str, ...]
    ref_name:        str | None
    vars_used:       tuple[int, ...]
    children:        tuple[int, int]      # (start, end) into child_lists; POST-ORDER
    flags:           int
    style_key:       str

class VarDataRecord(NamedTuple):
    hooks:      tuple[str, ...]
    imports:    tuple[ImportVarRecord, ...]                   # also full shape
    deps:       tuple[str, ...]
    components: tuple[str, ...]
    state:      str | None
    position:   int | None

class AppWrapRecord(NamedTuple):
    sort_key: int
    name:     str
    root:     int
```

```rust
// crates/reflex_py/src/wire.rs
#[derive(FromPyObject)]
pub struct WireImport(
    pub String,                      // 0 module
    pub Option<String>,              // 1 tag
    pub Option<String>,              // 2 alias
    pub bool,                        // 3 is_default
    pub Option<String>,              // 4 install_package
    pub bool,                        // 5 render
    pub bool,                        // 6 transpile
);

#[derive(FromPyObject)]
pub struct WireNode(
    pub u8,                          // 0  kind
    pub Option<String>,              // 1  tag
    pub Option<String>,              // 2  library
    pub Option<String>,              // 3  style
    pub Vec<(String, String)>,       // 4  rendered_props
    pub Vec<(String, String)>,       // 5  event_callbacks
    pub Vec<WireImport>,             // 6  imports — full ImportVar shape
    pub Vec<(String, u8)>,           // 7  hooks_internal
    pub Vec<(String, u8)>,           // 8  hooks_user
    pub Option<String>,              // 9  custom_code
    pub Vec<String>,                 // 10 dynamic_imports
    pub Option<String>,              // 11 ref_name
    pub Vec<u32>,                    // 12 vars_used
    pub (u32, u32),                  // 13 children (POST-ORDER indices)
    pub u8,                          // 14 flags
    pub String,                      // 15 style_key
);
```

`From<WireImport> for ImportEntry` maps every field into the existing Rust types (the additional flags become bits on `ImportEntry` or feed `bun install` accumulator directly). Parity tests assert: for every codegen corpus fixture, `bun install`'s package set matches today's, and rendered import lines are byte-identical.

Drift guard: `tests/units/compiler/test_wire_field_order.py` asserts `NodeRecord._fields` count + order matches `WireNode` arity.

---

## Rust entrypoint

```rust
fn compile_from_arena<'py>(
    &self,
    py: Python<'py>,
    nodes:         Vec<WireNode>,            // POST-ORDER from Python
    var_data:      Vec<WireVarData>,
    child_lists:   Vec<u32>,                  // post-order child indices
    text_value:    HashMap<u32, String>,      // keyed by post-order indices
    cond_test:     HashMap<u32, String>,
    foreach_iter:  HashMap<u32, String>,
    match_value:   HashMap<u32, String>,
    match_arms:    HashMap<u32, Vec<(String, u32)>>,
    match_default: HashMap<u32, u32>,
    expr_value:    HashMap<u32, String>,
    memo_key:      HashMap<u32, String>,
    // NOTE: `app_wraps: Vec<WireAppWrap>` arg deliberately OMITTED in PR A —
    // the Python freezer leaves `_APP_WRAPS` empty for now (handled by the
    // page-level Python `_get_all_app_wrap_components()` walk). Re-added in
    // a later phase if/when wraps are populated during construction.
    special_props: HashMap<u32, Vec<String>>,
    rename_props:  HashMap<u32, Vec<(String, String)>>,
    root:          u32,                       // post-order index of root
    route_ident:   &str, route: &str,
    title:         Option<&str>, meta_tags: Option<&Bound<'py, PyList>>,
    custom_code:   Option<Vec<String>>, hooks_body: Option<&str>,
) -> PyResult<(String, Vec<(String, String)>, Bound<'py, PyDict>)> {
    // Return shape in PR A: (page_js, memo_bodies, imports_dict).
    // No `app_wraps_dict` — that field stays out of the return contract
    // until the wire actually populates it.
    //
    // STEP 1: remap post-order → pre-order. Single DFS from root.
    let remap = build_postorder_to_preorder_map(&nodes, &child_lists, root);
    //         (returns Vec<u32> where remap[old_idx] = new_idx)

    // STEP 2: assemble Snapshot with remapped indices.
    let mut snapshot = build_snapshot_from_wire(
        nodes, var_data, child_lists,
        text_value, cond_test, foreach_iter,
        match_value, match_arms, match_default,
        expr_value, memo_key,
        special_props, rename_props,
        root, &remap,
    );
    snapshot.close_with_hashes();    // backward walk — invariant restored

    // STEP 3..N: unchanged downstream pipeline.
    let (page_js, memo_bodies) = py.allow_threads(move || {
        memoize_arena_pass(&mut snapshot);
        let page_js = emit_page_module_from_snapshot(&snapshot, route_ident, route, ...);
        let memo_bodies = emit_memo_bodies(&snapshot);
        (page_js, memo_bodies)
    });
    Ok((page_js, memo_bodies, build_imports_dict(&snapshot, py)?))
}
```

The post-order → pre-order remap is **not** in the diagram up top because the user doesn't experience it — it's an internal Rust step on the boundary between the wire and the Snapshot. The Snapshot's invariants are preserved end-to-end.

---

## Wire-extraction cost — measured, not asserted

Earlier drafts claimed "~24 µs marshaling per 150-node page" by hand-math. That number is **a hypothesis**, not a measurement. PyO3's `Vec<WireNode>` extraction recursively extracts each tuple, each nested `Vec<(String, String)>`, each `Option<String>` — non-trivial. **PR A must include a Criterion-style microbench** that measures:

1. Time to extract a hand-built 150-node `Vec<WireNode>` from Python
2. Time to extract all 15 args end-to-end
3. End-to-end `compile_from_arena` wall clock vs today's `compile_page_from_component_arena` on the same component

The ship gate for PR A is: extraction time per page **measured to be < 1 ms**, with the actual µs number written into this plan. No claims about "700×" until that number is in.

---

## App-wrap handling — stays in the page-level Python walk

The earlier "Rust collects app-wraps per node" path regressed 12% wall-clock; removing it brought us back to baseline. Same lesson applies here.

**Default**: `rust_pipeline.py` keeps the existing `component._get_all_app_wrap_components()` Python walk after `evaluate_and_freeze`. The Python walk is cheap (cached `_imports_cache`-style behavior on the Component side) and avoids reintroducing per-instance wrapper construction during freeze.

**Optional optimization (later)**: a class-level `_has_app_wraps: ClassVar[bool] = False` declaration. Classes that opt in get a per-instance call during `_record_self`; classes that don't get skipped entirely. Defer until measured.

The `app_wraps` slot on the wire (and `_APP_WRAPS` on the frame) stays in the schema for forward-compat but starts empty for now.

---

## Class-schema cache — class introspection only, no probes

Per Invariant 4, schema construction is purely declarative — read class attributes, scan `cls.__dict__` for overrides. No Component instances are created during cache build.

### Imports must be split into class-layer and instance-layer

The single most error-prone area in the legacy `_get_imports()` chain is that it returns **the merged set** of:

- the class library import (`{cls.library: [ImportVar(...)]}`)
- entries from `cls.lib_dependencies` (class-level)
- imports from `add_imports()` (class-level for non-overriders, possibly instance-dependent for overriders)
- VarData imports (instance-level — every Var referenced in props/style/events contributes its own deps)
- event-handler closure imports (instance-level)
- hook-VarData imports (instance-level via `_get_hooks_imports`)

If `_ClassSchema.imports_template` caches the *final* dict it will be wrong the moment an instance carries a Var. The schema must split:

- `class_imports`: the deterministic-from-class parts, frozen once per class (`cls.library`, `lib_dependencies`, the `add_imports()` result *if the class doesn't override or its override returned a class-constant value*).
- `instance_imports`: computed per-instance during `_record_self` from `frame.var_dedup` + event handlers + hooks.

`_record_self` merges the two right before pushing into `NodeRecord.imports`. The plan must call out this split explicitly so nobody collapses it into a single cached value.

```python
@dataclass(slots=True)
class _ClassSchema:
    kind:                int                # NodeKind discriminant
    tag:                 str | None
    library:             str | None
    style_key:           str
    prop_names:          tuple[str, ...]    # from cls.get_props() (classmethod)
    base_flags:          int
    # Override classification — class introspection, no probes:
    has_add_imports_override:        bool
    has_get_hooks_internal_override: bool
    has_get_style_override:          bool
    has_property_overrides:          frozenset[str]  # field names with @property
    has_getattribute_override:       bool
    # Class-layer caches — final imports/hooks are ALWAYS this UNION with
    # the instance-layer values computed at _record_self time.
    class_imports:       tuple[ImportVarRecord, ...]   # cls.library + lib_dependencies + safe add_imports
    class_hooks:         tuple[tuple[str, int], ...]   # only hooks that don't reference instance Vars
    style_class_default: str | None
```

`_build_class_schema(cls)`:

1. Walk `cls.__mro__` up to `Component` — `cls.__dict__.get(name)` for each override-detection key.
2. Read `cls.tag`, `cls.library`, `cls.lib_dependencies`, `cls.__qualname__`.
3. Call `cls.get_props()` (classmethod — no instance) → `prop_names`.
4. Build `class_imports` from:
   - `cls.library` (if set) → one `ImportVarRecord` with `tag = _resolve_import_var_tag(cls)`, `is_default = cls.is_default`, `install_package = cls.install_package or cls.library`, etc.
   - Each entry in `cls.lib_dependencies` → side-effect `ImportVarRecord` (tag=None, render=False).
   - If `not has_add_imports_override`: nothing more. If the override exists but is class-level constant (rare; opt-in via a declared `_add_imports_is_class_level = True` flag), include its result.
5. Same split for hooks: `class_hooks` only holds entries that don't depend on instance Vars.
6. Cache in `_CLASS_SCHEMA[cls]`.

`_record_self` import merge:
```python
imports = list(schema.class_imports)
for var_idx in vars_used:
    imports.extend(frame.var_data[var_idx].imports)
for handler_js in event_callback_bodies:
    imports.extend(_extract_handler_imports(handler_js))
# … merge + dedup into NodeRecord.imports
```

First-sighting class cost: ~5 attribute reads + one `get_props()` call. Single-digit microseconds. No `Component()` instantiation, no probe, no `suspended()` needed.

---

## Phases (revised — every High-severity item has a gate)

| # | Phase | ETA | Gates |
|---|---|---:|---|
| 0a | Rust: introduce a `snap.children(idx) -> impl Iterator<NodeIdx>` accessor on `Snapshot` while `children` remains a `Range<NodeIdx>` into `nodes`. **Migrate every consumer** (emit walks, memoize pass, close_with_hashes, every public `Snapshot::*` method) to use the accessor. Existing parent-before-children invariant unchanged. | 2-3d | All existing arena tests green. `grep -r 'node.children\b'` across the workspace returns zero direct field reads outside the accessor + the storage. |
| 0b | Rust: change underlying storage to `Snapshot.child_lists: Vec<NodeIdx>` side-table + `NodeSnapshot.children: Range<u32>` into it. Accessor implementation flips; consumers unchanged. | 1-2d | Same test suite green. Cargo bench: emit walks within ±1% of pre-0a. Hashing parity test on representative fixtures. |
| 1 | Rust: `wire::{WireImport, WireNode, WireVarData, WireAppWrap}` + `From` impls + `compile_from_arena` entrypoint **including the post-order→pre-order remap pass**. Hand-build NamedTuples in Python tests. Criterion microbench for extraction cost. Return tuple **omits** `app_wraps_dict` for PR A (always-empty for now — re-add in a later phase when populated). | 3-4d | (a) 4 trivial fixtures byte-identical JSX. (b) Microbench logs per-page extraction time directly into this plan file. (c) Remap fuzz test: random child-relation graphs roundtrip with all consumers seeing parent-before-child. (d) Import parity: every codegen corpus fixture's `bun install` package set + emitted import lines match today's byte-for-byte. |
| 2a | Python: `_records.py` NamedTuples (incl. `ImportVarRecord`) + `ContextVar`-based frame + `_active()` + `suspended()`. No `Component` change yet — write hand-built freezer that walks a tree post-mortem and produces a frame. | 2d | (a) The 4 trivial fixtures round-trip through the hand-built freezer → `compile_from_arena` → JSX, byte-identical. (b) Tests prove `with suspended():` discards recordings. (c) Tests prove `_recording` is nestable + ContextVar-isolated across threads/asyncio tasks. |
| 2b | Python: add the `_post_init` hook on `Component`. Cover Element + Fragment + literal Text only. **Microbench `Component()` construction with no active recording**: must show added cost ≤ 100 ns per construction on the user-app hot path. Numbers logged in plan. | 2d | (a) 4 trivial fixtures end-to-end parity (page() → freezer → JSX). (b) Component-construction microbench number in plan. (c) Existing test suite green (most tests construct Components outside any recording — they exercise the no-op path). |
| 3a | **Foreach + CustomComponent parity sub-phase** (highest-risk semantics). Tests 1-5 from §"Foreach / CustomComponent parity" — timing, style application, placeholder Var shape, error propagation, re-render idempotency. | 3-5d | All 5 parity tests green on both legacy + Python-freezer paths. |
| 3b | Per-kind dispatch in `_record_self` for the remaining variants — Vars (id-dedup), events, Cond, Match, style, hooks, refs, special/rename props, memo mode, title/meta wrapper. | 5-7d | (a) All 31 IR-completeness tests pass against Python-frozen output. (b) Full codegen corpus parity. |
| 4 | `_CLASS_SCHEMA` cache with class-introspection-only classification. Explicitly **separates class-derivable imports** (cls.library + lib_dependencies, cached on schema) **from instance-derivable imports** (VarData imports, event-handler imports, hooks imports — recomputed per node). | 2-3d | (a) `_get_imports`/`_get_hooks_internal` invoked ≤ 1× per *non-overriding* class per session. (b) Override classes still produce correct output via per-instance calls. (c) `@property` override on a declared field flips to `getattr` fallback. (d) Test: a class whose final imports depend on instance Vars sees those Vars' imports in the final per-node `imports` list. |
| 5 | `rust_pipeline.py` cuts over to `evaluate_and_freeze`. Legacy gated behind `REFLEX_LEGACY_FREEZE=1`. | 2-3d | **Both paths must pass the full unit + integration suite**: CI runs once with new freezer (default) and once with `REFLEX_LEGACY_FREEZE=1`. Both green to merge. |
| 6 | Delete the Rust PyO3-walking freezer (`freeze.rs`, most of `pyo3_reader.rs`, old `compile_page_from_component_arena`). | 1d | ~3,000 LoC of Rust removed. Legacy env flag becomes a no-op (logs a deprecation warning). |
| 7 | Re-profile; update `PROFILING_FINDINGS.md` §13. | 0.5d | wall ms/page, per-page extraction µs, and Component-construction ns recorded in plan. |

---

## Migration safety

- **`REFLEX_LEGACY_FREEZE=1`** keeps the old Rust freeze live during Phases 5-6. Rollback is one env var.
- **CI runs the full unit + integration suite in BOTH freezer modes** during the entire Phase 5-6 window. Default mode = Python freezer; second job sets `REFLEX_LEGACY_FREEZE=1` and re-runs. Either failing blocks merge.
- **`tests/units/compiler/test_arena_ir_parity.py`** — every codegen corpus fixture compiled both ways, byte-identical JSX required to merge.
- **31 IR-completeness tests** are the contract; they pass against current Rust freeze today, must pass against Python freezer after Phase 3.
- **Reentrancy tests** (Phase 2a):
  - Construct probes inside `with suspended():` — verify the frame's `nodes` length doesn't grow.
  - Start a nested `_recording()` inside another — verify the outer frame is untouched on inner pop.
  - Spawn two `asyncio.Task`s each with their own `_recording()` — verify their frames are isolated.
  - Spawn two threads each with their own `_recording()` — same isolation check.
- **Remap fuzz test** (Phase 1): generate random child relations + post-order indices in Python, run remap in Rust, verify (a) all NodeIdx refs in bounds, (b) every node reachable from `root`, (c) every parent comes before every descendant.
- **Component-construction microbench** (Phase 2b): run before and after the `_post_init` hook lands; the after-number must show ≤ 100 ns added per construction outside compile. If higher, the hook design changes (e.g. fast-path the ContextVar check via a C-level flag) before Phase 3.

---

## Risks (review-acknowledged)

| Risk | Mitigation |
|---|---|
| Schema probes pollute arena | **No probes in default path** (Invariant 4); if added later, must use `suspended()` |
| Control-flow components materialize bodies lazily | First-class per-kind dispatch + dedicated Phase 3a parity sub-phase with five tests (timing, style, placeholder Var, error propagation, idempotency) before the broad `_post_init` hook lands |
| Reentrance breaks under parallel routes / asyncio / threads | `ContextVar` from day one (Invariant 1) — each task/thread sees its own frame; nested same-task pushes are token-based; explicit Phase 2a tests cover asyncio + threading + nested cases |
| Post-order vs pre-order Snapshot invariants | Explicit Rust-side remap pass (Invariant 2). **Phase 0 split into 0a (accessor migration) + 0b (storage swap)** so consumers can't accidentally depend on the old layout. |
| Wire `(str, str)` import shape loses ImportVar metadata | Replaced with `ImportVarRecord` carrying module/tag/alias/is_default/install_package/render/transpile. Phase 1 parity gate: `bun install` package set + emitted import lines byte-identical |
| "1 PyO3 call" hides nested-tuple extraction cost | Phase 1 includes Criterion microbench; ship gate writes actual µs/page into this plan before Phase 2 starts |
| `_post_init` hook adds measurable cost outside compile | Phase 2b includes Component-construction microbench; ≤100 ns/construction is the hard ship gate. If exceeded, redesign the hook (e.g. C-level fast path) before continuing |
| App-wraps reintroduce per-node Component construction | Default keeps Python `_get_all_app_wrap_components` walk; PR A omits `app_wraps_dict` from the return shape; per-instance freezer call is a future opt-in |
| Class-schema cache conflates class-vs-instance imports | `_ClassSchema` explicitly holds only `class_imports`; final per-node imports are always `class_imports + instance_imports_from_vars_and_handlers`. Phase 4 test pins this for a class whose final imports include Var-derived entries |
| Probe-and-compare unsound | Default is class-introspection-only (Invariant 4); probe-and-compare deferred behind explicit flag |
| Subtree hash stability across freeze paths | Hash computed by Rust after remap — same input pre-order, same output bytes |
| Cutover regresses some uncovered case | CI runs full suite with `REFLEX_LEGACY_FREEZE=0` AND `=1` during Phase 5-6; either failing blocks merge |
| `_arena_idx` field name collides with subclass attr | Use `_reflex_arena_idx` (Pydantic `PrivateAttr` mangled name) |

---

## First PR scope (PR A)

Per the reviewer, PR A includes more than just the entrypoint:

- `Snapshot.child_lists` side-table; existing emit walks adapted; full arena test suite green.
- `wire::{WireNode, WireVarData, WireAppWrap}` tuple structs + `From` impls.
- `compile_from_arena` PyO3 method **including the post-order → pre-order remap pass**.
- Python test that hand-builds a post-order NamedTuple sequence for `rx.box(rx.text("a"), rx.text("b"))`, calls `compile_from_arena`, asserts byte-identical JSX vs the current Rust freeze.
- Criterion microbench: synthetic 150-node and 350-node trees, measure end-to-end `compile_from_arena` wall time and the share spent in PyO3 extraction. The numbers go into this plan before Phase 2 starts.
- Fuzz test: post-order-indices with random child relations → remap roundtrip preserves parent-before-child ordering for every Snapshot consumer.

If PR A lands with green tests and the microbench numbers in this file, Phases 2-7 are mechanical fill-in following the per-kind dispatch table and the recording-stack contract. If it doesn't, we learn before touching `Component._post_init`.

---

## What this plan deliberately defers

- **Probe-and-compare classification** — too risky for default; class-introspection-only suffices for ~95% of components.
- **Parallel route compilation** — orthogonal; the frame-stack already supports it (push two frames in two threads with thread-locality), but no implementation in scope here.
- **Free-threaded Python 3.13+** — same; revisit once Phase 7 numbers are in.
- **Per-class app-wrap opt-in** — small optional optimization; defer until app-wrap cost is the bottleneck.
