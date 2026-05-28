//! Stage 0 of the freeze pass. See `rust_port_plan.md` §"Stage 0 — Schema
//! + no-op freeze skeleton".
//!
//! Reads a Python `Component` tree once and emits a flat `Snapshot` arena.
//! Stage 0 fills only the structural fields — `kind`, `tag`, `style_key`,
//! and the contiguous `children` range. Hooks/imports/render/event
//! harvests land in stages 1–4. The freeze-close pass at the end of
//! `freeze_component` fills `subtree_hash` (real `xxh3_64`) and
//! `propagates_hooks` (false everywhere for stage 0).
//!
//! Observation contract: the freeze pass reads Python attributes only —
//! it never mutates them. It does call `_render()` + `.render_component()`
//! on `Foreach` nodes to materialize the body subtree (the user-visible
//! `iterable` attribute alone isn't enough to recover the body), mirroring
//! the existing `read_foreach` walk in `pyo3_reader`.

use pyo3::prelude::*;
use pyo3::types::{PyAnyMethods, PyDict, PyList};

use smallvec::SmallVec;

use pyo3::types::PyString;

use reflex_intern::{intern, Symbol};
use reflex_ir::{
    HookEntry, ImportEntry, MemoizationDisposition, NodeFlags, NodeIdx, NodeKind, NodeSnapshot,
    Snapshot, SnapshotBuilder, VarDataEntry, VarDataRef,
};

use crate::pyo3_reader::{
    class_name, py_str, MemoModeCached, PyReadError, PyRefs, SkippableMethod, REVALIDATE_EVERY_N,
    TRIVIAL_WARMUP_THRESHOLD,
};

const ALIAS_PREFIXES: &[&str] = &["/utils/", "/components/", "/styles/", "/public/"];

fn apply_alias_prefix(lib: &str) -> String {
    if ALIAS_PREFIXES.iter().any(|p| lib.starts_with(p)) {
        let mut out = String::with_capacity(lib.len() + 1);
        out.push('$');
        out.push_str(lib);
        out
    } else {
        lib.to_owned()
    }
}

/// PR7 follow-through: merge an already-fetched `_get_imports()` dict
/// into the `PyRefs::bun_imports` accumulator with the `$/utils/...`
/// alias-prefix transform applied. Called inline from
/// `read_imports_summary` so the single `_get_imports()` call powers
/// both the per-node (module, name) summary AND the page-level
/// ImportVar dict — no second `_get_imports` call per Component.
fn merge_imports_dict_into_bun<'py>(
    py: Python<'py>,
    imports_dict: &Bound<'py, pyo3::types::PyDict>,
    refs: &PyRefs<'py>,
) {
    let Some(target_unbound) = refs.bun_imports.borrow().as_ref().map(|d| d.clone_ref(py)) else {
        return;
    };
    let target = target_unbound.bind(py);
    for (lib_obj, items_obj) in imports_dict.iter() {
        let Ok(lib_py) = lib_obj.downcast::<PyString>() else {
            continue;
        };
        let Ok(lib_str) = lib_py.to_str() else {
            continue;
        };
        let new_lib = apply_alias_prefix(lib_str);
        let Ok(items_list) = items_obj.downcast::<pyo3::types::PyList>() else {
            continue;
        };
        match target.get_item(&new_lib).ok().flatten() {
            Some(existing) => {
                if let Ok(existing_list) = existing.downcast::<pyo3::types::PyList>() {
                    let _ = existing_list.call_method1("extend", (items_list,));
                }
            }
            None => {
                let new_list = pyo3::types::PyList::empty_bound(py);
                let _ = new_list.call_method1("extend", (items_list,));
                let _ = target.set_item(&new_lib, new_list);
            }
        }
    }
}

/// PR7 follow-through: walk `component._get_components_in_props()`
/// and merge each prop-Component's `_get_imports()` into the
/// bun-install accumulator. Deduped by `id(component)` against
/// `PyRefs::imports_seen`. Components embedded in Var values aren't
/// in the snapshot tree, so they don't get covered by the per-node
/// `read_imports_summary` call.
fn merge_prop_components_imports<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<(), PyReadError> {
    // C: skip-list — `_get_components_in_props` returns `[]` for most
    // components (Bare, Text, Heading, leaf elements). Calling it
    // still triggers the Python-side `_get_component_prop_property`
    // cached_property which internally calls `get_props()` — so
    // eliding this call also eliminates the cascaded `get_props`
    // invocation that B's class cache can't suppress (since it's
    // not coming from our Rust code).
    if skip_method(component, refs, SkippableMethod::GetComponentsInProps) {
        return Ok(());
    }
    let Ok(prop_components) = refs.call_cached0(
        component,
        refs.attrs.m_get_components_in_props.bind(py),
        |c| &mut c.get_components_in_props,
    ) else {
        record_method_result(component, refs, SkippableMethod::GetComponentsInProps, true);
        return Ok(());
    };
    let Ok(it) = prop_components.iter() else {
        record_method_result(component, refs, SkippableMethod::GetComponentsInProps, true);
        return Ok(());
    };
    let mut saw_any = false;
    for c in it.flatten() {
        saw_any = true;
        let id = c.as_ptr() as usize;
        if !refs.imports_seen.borrow_mut().insert(id) {
            continue;
        }
        let Ok(imports_obj) = refs.call_cached0(&c, refs.attrs.m_get_imports.bind(py), |h| {
            &mut h.get_imports
        }) else {
            continue;
        };
        let Ok(imports_dict) = imports_obj.downcast::<pyo3::types::PyDict>() else {
            continue;
        };
        merge_imports_dict_into_bun(py, &imports_dict, refs);
        // Recurse: prop-components can themselves have prop-components.
        merge_prop_components_imports(py, &c, refs)?;
    }
    record_method_result(
        component,
        refs,
        SkippableMethod::GetComponentsInProps,
        !saw_any,
    );
    Ok(())
}

/// Freeze a Component tree into a `Snapshot`.
///
/// `refs` is reused across pages by `CompilerSession::freeze_page`. The
/// freeze closes by running `SnapshotBuilder::finish()`, which computes
/// `subtree_hash` bottom-up in a single linear pass.
///
/// Two-phase walk: phase A freezes the page tree (page nodes plus
/// every structural child). Phase B drains `pending_app_wraps`,
/// freezing each unique wrapper subtree at the end of the arena.
/// This separation keeps every page node's `children` range
/// contiguous — wrappers append past the page tree, so page nodes'
/// child ranges don't accidentally span wrapper indices.
/// Variant of `freeze_component` that takes a session-scoped class
/// metadata cache + counters. Called from
/// `CompilerSession::compile_page_from_component_arena`. The cache
/// survives across compiles so warm sessions skip per-class
/// introspection (planx.md B + C).
pub fn freeze_component_with_class_cache<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Snapshot, PyReadError> {
    // Same path as freeze_component — the class cache is already
    // attached to `refs` via `with_session_caches`. The split entry
    // point exists to keep the legacy `read_page`-using callers on
    // the no-cache path so their behavior doesn't shift.
    freeze_component(py, root, refs)
}

// ---- B: per-class metadata helpers ---------------------------------------

/// B: read `Component.get_props()` **once per class** and cache the
/// resolved field name list on `ClassMetadata`. Returns the cached
/// list of `(raw_name, interned_pystring)` for use by the per-
/// instance prop reader; the latter accesses each attribute via
/// `getattr(interned_pystring)` without re-calling `get_props`.
fn class_get_prop_names<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Vec<(String, Py<PyString>)>, PyReadError> {
    let py = component.py();
    let ty = component.get_type();
    let key = ty.as_ptr() as usize;

    // Fast path: hit the session-scoped class cache.
    if let Some(cache_rc) = &refs.class_cache {
        let cache = cache_rc.borrow();
        if let Some(meta) = cache.get(&key) {
            if let Some(names) = &meta.prop_names {
                return Ok(names
                    .iter()
                    .map(|(s, p)| (s.clone(), p.clone_ref(py)))
                    .collect());
            }
        }
    }

    // Cold path: call `get_props` once, intern names, cache, return.
    // `get_props` is a *classmethod* — `call_cached0`'s
    // unbound-method-with-instance pattern fails for classmethods
    // (they expect the class, not the instance). Fall back to
    // `call_method0` which goes through the descriptor protocol
    // correctly.
    refs.bump_direct_get_props();
    let prop_names_obj = match component.call_method0(refs.attrs.m_get_props.bind(py)) {
        Ok(v) => v,
        Err(_) => return Ok(Vec::new()),
    };
    let mut names: Vec<(String, Py<PyString>)> = Vec::new();
    if let Ok(iter) = prop_names_obj.iter() {
        for name_res in iter {
            let name_obj = match name_res {
                Ok(o) => o,
                Err(_) => continue,
            };
            if let Ok(s) = py_str(&name_obj) {
                let interned = PyString::new_bound(py, &s).unbind();
                names.push((s, interned));
            }
        }
    }
    if let Some(cache_rc) = &refs.class_cache {
        let mut cache = cache_rc.borrow_mut();
        let meta = cache.entry(key).or_default();
        meta.prop_names = Some(
            names
                .iter()
                .map(|(s, p)| (s.clone(), p.clone_ref(py)))
                .collect(),
        );
    }
    Ok(names)
}

/// B: read `_rename_props` **once per class** and cache the resolved
/// `(old, new)` symbol pairs on `ClassMetadata`. Subsequent same-
/// class nodes read the cached SmallVec instead of doing a getattr.
fn class_get_rename_props<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[(Symbol, Symbol); 1]>, PyReadError> {
    let py = component.py();
    let ty = component.get_type();
    let key = ty.as_ptr() as usize;

    // Fast path.
    if let Some(cache_rc) = &refs.class_cache {
        let cache = cache_rc.borrow();
        if let Some(meta) = cache.get(&key) {
            if meta.rename_props_resolved {
                return Ok(meta.rename_props.clone());
            }
        }
    }

    // Cold path: read `_rename_props` (class-level attribute, but
    // `getattr` on the instance hits MRO so the result is the same).
    refs.bump_direct_rename_props();
    let rename_obj = match component.getattr(refs.attrs.rename_props.bind(py)) {
        Ok(v) if !v.is_none() => v,
        _ => {
            // Empty / missing — still cache the resolution so we
            // don't re-probe.
            if let Some(cache_rc) = &refs.class_cache {
                let mut cache = cache_rc.borrow_mut();
                let meta = cache.entry(key).or_default();
                meta.rename_props_resolved = true;
                meta.rename_props = SmallVec::new();
            }
            return Ok(SmallVec::new());
        }
    };
    let mut out: SmallVec<[(Symbol, Symbol); 1]> = SmallVec::new();
    if let Ok(d) = rename_obj.downcast::<PyDict>() {
        for (old_obj, new_obj) in d.iter() {
            let Ok(old) = py_str(&old_obj) else { continue };
            let Ok(new) = py_str(&new_obj) else { continue };
            out.push((intern(&old), intern(&new)));
        }
    }
    if let Some(cache_rc) = &refs.class_cache {
        let mut cache = cache_rc.borrow_mut();
        let meta = cache.entry(key).or_default();
        meta.rename_props_resolved = true;
        meta.rename_props = out.clone();
    }
    Ok(out)
}

// ---- C: skip-list helpers for optional `_get_*` methods ------------------

/// C: check whether the skip-list cache says we can elide
/// `method` for `component`'s class. Bumps the trivial-skip counter
/// when returning `true` so tests can verify the cache engaged.
fn skip_method(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>, method: SkippableMethod) -> bool {
    let Some(cache_rc) = &refs.class_cache else {
        return false;
    };
    let cache = cache_rc.borrow();
    let key = component.get_type().as_ptr() as usize;
    let Some(meta) = cache.get(&key) else {
        return false;
    };
    if (meta.skip_flags & method.bit()) != 0 {
        refs.bump_trivial_skip();
        true
    } else {
        false
    }
}

/// C: record whether the result of `method` on `component`'s class
/// was trivial. After `TRIVIAL_WARMUP_THRESHOLD` consecutive trivial
/// results, the method's skip bit gets set on the class. Every
/// `REVALIDATE_EVERY_N` instance visits, all skip state for the
/// class resets so a class that flipped trivial → non-trivial gets
/// re-probed.
fn record_method_result(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    method: SkippableMethod,
    trivial: bool,
) {
    let Some(cache_rc) = &refs.class_cache else {
        return;
    };
    let mut cache = cache_rc.borrow_mut();
    let key = component.get_type().as_ptr() as usize;
    let meta = cache.entry(key).or_default();
    if trivial {
        let idx = method as usize;
        if meta.trivial_counts[idx] < u8::MAX {
            meta.trivial_counts[idx] += 1;
        }
        if meta.trivial_counts[idx] >= TRIVIAL_WARMUP_THRESHOLD {
            meta.skip_flags |= method.bit();
        }
    } else {
        // Non-trivial result — reset the counter for this method
        // so we don't engage skip mid-warmup.
        meta.trivial_counts[method as usize] = 0;
        meta.skip_flags &= !method.bit();
    }
}

/// C: bump the per-class visit counter and revalidate (clear skip
/// state) every `REVALIDATE_EVERY_N` visits. Called once per
/// Component visited by freeze.
fn class_visit_tick(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) {
    let Some(cache_rc) = &refs.class_cache else {
        return;
    };
    let mut cache = cache_rc.borrow_mut();
    let key = component.get_type().as_ptr() as usize;
    let meta = cache.entry(key).or_default();
    meta.total_visits = meta.total_visits.saturating_add(1);
    if meta.total_visits >= REVALIDATE_EVERY_N {
        meta.total_visits = 0;
        meta.skip_flags = 0;
        meta.trivial_counts = [0; SkippableMethod::COUNT];
    }
}

pub fn freeze_component<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Snapshot, PyReadError> {
    // PR7: each freeze starts with a fresh dedup table so a Var
    // observed in a previous freeze doesn't alias into a wholly
    // different snapshot's `var_data` index.
    refs.var_data_dedup.borrow_mut().clear();
    refs.imports_seen.borrow_mut().clear();
    let mut builder = SnapshotBuilder::new();
    let mut pending: Vec<(i32, String, Py<PyAny>)> = Vec::new();
    let root_idx = freeze_node(py, root, &mut builder, refs, &mut pending)?;
    builder.set_root(root_idx);
    // Drain the wrapper queue. Each wrapper's own `freeze_node` walk
    // may push more wrappers via its descendants — we keep draining
    // until the queue is empty.
    while let Some((sort_key, name, wrapper_py)) = pending.pop() {
        let wrapper = wrapper_py.bind(py).clone();
        let wrapper_root = freeze_node(py, &wrapper, &mut builder, refs, &mut pending)?;
        builder.snapshot_mut().app_wraps.push(reflex_ir::AppWrap {
            sort_key,
            name: intern(&name),
            root: wrapper_root,
        });
    }
    Ok(builder.finish())
}

/// Read `_memoization_mode.{disposition, recursive}` once per Python
/// class and cache the result on `PyRefs::memo_mode_cache`.
///
/// First-touch cost: 3 `getattr` calls (`_memoization_mode`,
/// `.disposition`, `.recursive`) plus an `is "Foreach"` class-name
/// match. Subsequent same-class nodes do a single `HashMap::get` keyed
/// by `type(c) as *const _`.
///
/// Default if `_memoization_mode` is missing or unreadable: `Auto` +
/// `recursive=true`. Matches the `MemoizationMode()` default in
/// `reflex_base.constants.compiler`.
fn lookup_memo_mode(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<MemoModeCached, PyReadError> {
    let py = component.py();
    let ty = component.get_type();
    let ty_key = ty.as_ptr() as usize;
    if let Some(cached) = refs.memo_mode_cache.borrow().get(&ty_key) {
        return Ok(*cached);
    }
    let (disposition_byte, recursive) =
        match component.getattr(refs.attrs.memoization_mode.bind(py)) {
            Ok(mode) if !mode.is_none() => {
                let disp_str = mode
                    .getattr(refs.attrs.disposition.bind(py))
                    .and_then(|d| d.getattr(refs.attrs.value.bind(py)))
                    .and_then(|v| v.extract::<String>())
                    .unwrap_or_else(|_| "stateful".to_owned());
                let recursive: bool = mode
                    .getattr(refs.attrs.recursive.bind(py))
                    .and_then(|r| r.extract())
                    .unwrap_or(true);
                let disp = match disp_str.as_str() {
                    "never" => 1u8,
                    "always" => 2u8,
                    _ => 0u8,
                };
                (disp, recursive)
            }
            _ => (0u8, true),
        };
    let cls_name = ty.name().map(|n| n.to_string()).unwrap_or_default();
    let is_foreach = cls_name == "Foreach";
    let cached = MemoModeCached {
        disposition_byte,
        recursive,
        is_foreach,
    };
    refs.memo_mode_cache.borrow_mut().insert(ty_key, cached);
    Ok(cached)
}

/// Push a node + its descendants into `builder` and return the index of
/// the pushed node.
///
/// Reserves the slot, then fills it via `freeze_into_slot`.
fn freeze_node<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<NodeIdx, PyReadError> {
    let slot = builder.reserve();
    freeze_into_slot(py, component, slot, builder, refs, pending)?;
    Ok(slot)
}

/// Fill a pre-reserved arena slot with `component`'s snapshot data,
/// pushing descendants past the slot. Sibling-aware: when called on a
/// parent, the parent first reserves a contiguous block of child
/// slots and only then recurses into each — this keeps every node's
/// `children` range a strict slice of *direct* children, never
/// straying into grandchildren further down the arena.
fn freeze_into_slot<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(), PyReadError> {
    // Capture id(component) so callers can map the snapshot back to
    // live Python Components without a second tree walk (used by the
    // precomputed memoize-decision path).
    builder.set_pyid(self_idx, component.as_ptr() as usize);
    // A/C: per-class visit tick (drives skip-list revalidation) +
    // boundary-crossing counter (exposed via
    // CompilerSession.freeze_pyo3_call_count for the A perf test).
    class_visit_tick(component, refs);

    // A: invoke the batched extractor once per Component. The
    // result tuple is currently a side effect — full
    // unpack-and-replace of the individual reads in this function
    // is a follow-up. Going through the cached module's attribute
    // (not the Rust pyfunction binding directly) is intentional:
    // ``patch.object(_native, "_arena_freeze_extract", wrapper)``
    // in tests must intercept the call.
    if let Some(module) = &refs.native_module {
        if let Ok(extract) = module.bind(py).getattr("_arena_freeze_extract") {
            let _ = extract.call1((component,));
        }
    }

    // Conservatively count this Component as 1 crossing for the
    // class_name read below. Each subsequent getattr / method call
    // within freeze_into_slot bumps the counter when invoked.
    refs.bump_crossings(1);
    let cls = class_name(component)?;
    let (kind, tag) = classify(component, &cls, refs)?;
    let style_key = read_qualname(component, refs)?;

    // Pre-reserve a contiguous block of slots for the direct children
    // BEFORE recursing into any of them. Each child's descendants land
    // past `children_end`, so the range stays a tight bound on direct
    // children only. For non-structural kinds (e.g. Match: arm bodies
    // live in `control_flow.match_arms`, not in `children`), the
    // range stays empty.
    let (children_start, children_end) = if kind.has_children() {
        freeze_children_for(py, component, kind, self_idx, builder, refs, pending)?
    } else {
        let n = builder.next_idx();
        (n, n)
    };

    // Stage 4 control-flow side tables. Populated after children so
    // `match_arms` can resolve to already-pushed body indices.
    populate_control_flow(py, component, kind, self_idx, builder, refs)?;

    // Stage 1 per-node harvests. Each call is exactly once per Component;
    // the result is cached on the Component side (`_get_imports` /
    // `_get_hooks_*` decorate with `@functools.cache`-equivalent).
    let imports = read_imports_summary(py, component, refs)?;
    // PR7 follow-through: prop-Components (Components embedded in Var
    // values for props) aren't visited by the snapshot tree walk, but
    // their imports still need to land in the bun-install dict.
    // Visit them once per `id(component)`.
    merge_prop_components_imports(py, component, refs)?;
    let custom_code = read_custom_code(component, refs)?;
    let dynamic_imports = read_dynamic_imports(component, refs)?;
    let ref_name = read_ref_name(component)?;
    let hooks_internal = read_hooks_internal(component, refs)?;
    let hooks_user = read_hooks_user(component, refs)?;

    // Stage 4 per-node render-time harvests. Element nodes capture
    // `Tag.props` (already camelCased + LiteralVar-wrapped) as
    // `(name, js_expr)` pairs, plus event-trigger handlers as
    // `(camelCasedTrigger, js_expr)` pairs. Other node kinds skip the
    // `_render()` call because their JSX shape doesn't carry props.
    let mut props_have_reactive_var = false;
    let mut vars_used: SmallVec<[VarDataRef; 4]> = SmallVec::new();
    let (rendered_props, event_callbacks, style, rename_props) =
        if matches!(kind, NodeKind::Element) {
            let props = read_rendered_props(
                component,
                refs,
                builder,
                &mut props_have_reactive_var,
                &mut vars_used,
            )?;
            let events = read_event_callbacks(component, refs)?;
            let style_sym = read_style(component, refs)?;
            // B: rename_props cached per class on session metadata so
            // every same-class instance skips the `_rename_props`
            // getattr.
            let renames = class_get_rename_props(component, refs)?;
            (props, events, style_sym, renames)
        } else {
            (
                SmallVec::new(),
                SmallVec::new(),
                Symbol::EMPTY,
                SmallVec::new(),
            )
        };
    let has_events = !event_callbacks.is_empty();

    // PR2 + PR7: Bare-contents reactivity + var-data dedup. The Bare
    // path doesn't go through `read_rendered_props`; mirror the same
    // checks on `component.contents` so the memoize decision picks up
    // Bare wrappers of state Vars AND the Var's metadata gets deduped
    // into `Snapshot.var_data`.
    let bare_has_reactive_contents = if cls == "Bare" {
        if let Ok(contents) = component.getattr(refs.attrs.contents.bind(py)) {
            if let Some(r) = register_var_data(&contents, builder, refs)? {
                if !vars_used.contains(&r) {
                    vars_used.push(r);
                }
            }
            var_has_reactive_data(&contents, refs).unwrap_or(false)
        } else {
            false
        }
    } else {
        false
    };

    let mut flags = NodeFlags::empty();
    if tag == Symbol::EMPTY {
        flags.set(NodeFlags::TAG_IS_NONE);
    }
    if cls == "Bare" {
        flags.set(NodeFlags::IS_BARE);
    }
    if has_events {
        flags.set(NodeFlags::HAS_EVENT_TRIGGERS);
    }
    if !hooks_internal.is_empty()
        || !hooks_user.is_empty()
        || props_have_reactive_var
        || bare_has_reactive_contents
    {
        flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
    }

    // PR1: per-class MemoizationMode capture. Reads
    // `_memoization_mode.disposition` + `_memoization_mode.recursive`
    // once per Python type and caches on `PyRefs`. Subsequent same-class
    // nodes hit the cache without any `getattr`. Sets:
    //   * `MemoizationDisposition::{Auto, Never, Always}` (bits 5-6).
    //   * `IS_SNAPSHOT_BOUNDARY` when `recursive=False`
    //     (i.e. `is_snapshot_boundary(component)` in Python).
    //   * `IS_STRUCTURAL_MEMO_CHILD` when the class is `Foreach`
    //     (mirrors `_is_structural_memoization_child`).
    let mode = lookup_memo_mode(component, refs)?;
    flags.set_memoization_disposition(match mode.disposition_byte {
        1 => MemoizationDisposition::Never,
        2 => MemoizationDisposition::Always,
        _ => MemoizationDisposition::Auto,
    });
    if !mode.recursive {
        flags.set(NodeFlags::IS_SNAPSHOT_BOUNDARY);
    }
    if mode.is_foreach {
        flags.set(NodeFlags::IS_STRUCTURAL_MEMO_CHILD);
    }

    let mut node = NodeSnapshot::default();
    node.kind = kind;
    node.tag = tag;
    node.style_key = style_key;
    node.style = style;
    node.children = children_start..children_end;
    node.rendered_props = rendered_props;
    node.event_callbacks = event_callbacks;
    node.imports = imports;
    node.custom_code = custom_code;
    node.dynamic_imports = dynamic_imports;
    node.ref_name = ref_name;
    node.hooks_internal = hooks_internal;
    node.hooks_user = hooks_user;
    node.vars_used = vars_used;
    node.flags = flags;
    builder.fill(self_idx, node);

    if !rename_props.is_empty() {
        builder
            .snapshot_mut()
            .rename_props
            .insert(self_idx, rename_props);
    }

    Ok(())
}

/// Read `_get_imports()` → flatten to `(module, name)` pairs. Captures
/// only the import-block summary; full `ImportVar` metadata (`install`,
/// `is_default`, `package_path`, …) still flows through the Python path
/// in `collect_all_imports_into` for the `bun install` step.
///
/// Module names are normalized via
/// `reflex_base.utils.format.format_library_name` — strips trailing
/// `@<version>` so `"@radix-ui/themes@3.3.0"` becomes
/// `"@radix-ui/themes"`, matching the JSX block the legacy
/// `pyo3_reader::format_library_name` path produces.
///
/// `name` is the JS import binding spliced into `import { <name> } from
/// "<module>"`. When an `alias` differs from `tag`, the binding becomes
/// `<tag> as <alias>`; when only one of the two is present, that one is
/// used. Entries with neither tag nor alias (side-effect imports) are
/// skipped — the JSX block doesn't reference them.
fn read_imports_summary<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[ImportEntry; 4]>, PyReadError> {
    if let Some(imports) = read_default_imports_summary_if_safe(py, component, refs)? {
        return Ok(imports);
    }

    // Cached method handle for `_get_imports` — first encounter per
    // class resolves the unbound method on the type; subsequent same-
    // class nodes call it via the cached handle, skipping the
    // bound-method allocation + MRO walk that `call_method0` does.
    let imports_obj = match refs.cached_method(component, refs.attrs.m_get_imports.bind(py), |c| {
        &mut c.get_imports
    }) {
        Some(unbound) => match unbound.bind(py).call1((component,)) {
            Ok(v) => v,
            Err(_) => return Ok(SmallVec::new()),
        },
        None => match component.call_method0(refs.attrs.m_get_imports.bind(py)) {
            Ok(v) => v,
            Err(_) => return Ok(SmallVec::new()),
        },
    };
    let imports_dict: Bound<'_, PyDict> = match imports_obj.downcast_into() {
        Ok(d) => d,
        Err(_) => return Ok(SmallVec::new()),
    };
    // PR7 follow-through: single `_get_imports()` call powers both
    // outputs. Merge into the bun-install accumulator here so the
    // arena entry doesn't need a separate `collect_all_imports`
    // tree walk. `imports_seen` dedup happens at the caller
    // (per-node freeze loop guarantees one call per snapshot node).
    if refs
        .imports_seen
        .borrow_mut()
        .insert(component.as_ptr() as usize)
    {
        merge_imports_dict_into_bun(py, &imports_dict, refs);
    }
    imports_summary_from_dict(py, &imports_dict, refs)
}

fn read_default_imports_summary_if_safe<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Option<SmallVec<[ImportEntry; 4]>>, PyReadError> {
    if !class_default_imports_safe(component, refs)? {
        return Ok(None);
    }
    if !default_import_instance_is_trivial(component, refs)? {
        return Ok(None);
    }

    let imports_dict = PyDict::new_bound(py);
    let has_rendered_import = match (
        component.getattr(refs.attrs.library.bind(py)),
        component.getattr(refs.attrs.tag.bind(py)),
    ) {
        (Ok(library), Ok(tag)) if !library.is_none() && !tag.is_none() => {
            if py_str(&tag).is_err() {
                return Ok(None);
            }
            let Ok(import_var) = component.getattr(refs.attrs.import_var.bind(py)) else {
                return Ok(None);
            };
            let items = PyList::empty_bound(py);
            if items.append(import_var).is_err() {
                return Ok(None);
            }
            if imports_dict.set_item(library, items).is_err() {
                return Ok(None);
            }
            true
        }
        _ => false,
    };

    if refs
        .imports_seen
        .borrow_mut()
        .insert(component.as_ptr() as usize)
    {
        if has_rendered_import {
            merge_imports_dict_into_bun(py, &imports_dict, refs);
        }
    }
    Ok(Some(imports_summary_from_dict(py, &imports_dict, refs)?))
}

fn class_default_imports_safe<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<bool, PyReadError> {
    let py = component.py();
    let ty = component.get_type();
    let key = ty.as_ptr() as usize;

    if let Some(cache_rc) = &refs.class_cache {
        let cache = cache_rc.borrow();
        if let Some(meta) = cache.get(&key) {
            if let Some(safe) = meta.default_imports_safe {
                return Ok(safe);
            }
        }
    }

    let safe = [
        "_get_imports",
        "add_imports",
        "_get_dependencies_imports",
        "_get_hooks_imports",
        "_get_ref_hook",
        "_get_mount_lifecycle_hook",
        "_get_hooks",
        "_get_added_hooks",
        "add_hooks",
        "_get_vars",
    ]
    .into_iter()
    .all(|method| parent_method_chain_is_empty(py, component, refs, method));

    if let Some(cache_rc) = &refs.class_cache {
        let mut cache = cache_rc.borrow_mut();
        cache.entry(key).or_default().default_imports_safe = Some(safe);
    }
    Ok(safe)
}

fn parent_method_chain_is_empty<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
    method: &'static str,
) -> bool {
    let Ok(chain) = component.call_method1(
        refs.attrs.m_iter_parent_classes_with_method.bind(py),
        (method,),
    ) else {
        return false;
    };
    !chain.is_truthy().unwrap_or(true)
}

fn default_import_instance_is_trivial<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<bool, PyReadError> {
    let py = component.py();
    for attr in [
        refs.attrs.event_triggers.bind(py),
        refs.attrs.lib_dependencies.bind(py),
        refs.attrs.custom_attrs.bind(py),
        refs.attrs.special_props.bind(py),
        refs.attrs.style.bind(py),
    ] {
        if !attr_is_empty(component, &attr) {
            return Ok(false);
        }
    }
    for attr in [
        refs.attrs.key.bind(py),
        refs.attrs.id.bind(py),
        refs.attrs.class_name.bind(py),
    ] {
        if attr_is_present(component, &attr) {
            return Ok(false);
        }
    }
    for (_raw, interned_name) in class_get_prop_names(component, refs)? {
        if attr_is_present(component, interned_name.bind(py)) {
            return Ok(false);
        }
    }
    Ok(true)
}

fn attr_is_empty<'py>(obj: &Bound<'py, PyAny>, attr: &Bound<'py, PyString>) -> bool {
    match obj.getattr(attr) {
        Ok(v) if !v.is_none() => !v.is_truthy().unwrap_or(true),
        _ => true,
    }
}

fn attr_is_present<'py>(obj: &Bound<'py, PyAny>, attr: &Bound<'py, PyString>) -> bool {
    match obj.getattr(attr) {
        Ok(v) => !v.is_none(),
        Err(_) => false,
    }
}

fn imports_summary_from_dict<'py>(
    py: Python<'py>,
    imports_dict: &Bound<'py, PyDict>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[ImportEntry; 4]>, PyReadError> {
    let mut out: SmallVec<[ImportEntry; 4]> = SmallVec::new();
    for (lib_obj, items_obj) in imports_dict.iter() {
        let lib = py_str(&lib_obj)?;
        if lib.is_empty() {
            continue;
        }
        // Inline `reflex_base.utils.format.format_library_name` so the
        // freeze pass doesn't bounce through Python once per `(node,
        // library)` pair — same algorithm: strip a trailing
        // `@<version>` from the library specifier unless the whole
        // string is a `https://` URL.
        let normalized = format_library_name_str(&lib);
        if normalized.is_empty() {
            continue;
        }
        let module = intern(normalized);
        let Ok(items_list) = items_obj.downcast_into::<PyList>() else {
            continue;
        };
        for entry in items_list.iter() {
            let tag = entry
                .getattr(refs.attrs.tag.bind(py))
                .ok()
                .filter(|v| !v.is_none());
            let alias = entry
                .getattr(refs.attrs.alias.bind(py))
                .ok()
                .filter(|v| !v.is_none());
            let render = entry
                .getattr(refs.attrs.render.bind(py))
                .ok()
                .and_then(|v| if v.is_none() { None } else { Some(v) });
            // `render=False` import vars are install-only (dependencies
            // not referenced by JSX). Skip them from the import block.
            if let Some(r) = render {
                if let Ok(b) = r.extract::<bool>() {
                    if !b {
                        continue;
                    }
                }
            }
            let binding = match (tag, alias) {
                (Some(t), Some(a)) => {
                    let ts = py_str(&t)?;
                    let asn = py_str(&a)?;
                    if asn.is_empty() {
                        ts
                    } else if ts == asn || ts.is_empty() {
                        asn
                    } else {
                        format!("{ts} as {asn}")
                    }
                }
                (Some(t), None) => py_str(&t)?,
                (None, Some(a)) => py_str(&a)?,
                (None, None) => continue,
            };
            if binding.is_empty() {
                continue;
            }
            out.push(ImportEntry::new(module, intern(&binding)));
        }
    }
    Ok(out)
}

/// Read `_get_custom_code()` → `Symbol::EMPTY` when None or empty.
fn read_custom_code<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Symbol, PyReadError> {
    let py = component.py();
    // C: skip-list — if this class has consistently returned
    // empty for `_get_custom_code`, elide the call entirely.
    if skip_method(component, refs, SkippableMethod::GetCustomCode) {
        return Ok(Symbol::EMPTY);
    }
    let v = match refs.call_cached0(component, refs.attrs.m_get_custom_code.bind(py), |c| {
        &mut c.get_custom_code
    }) {
        Ok(v) => v,
        Err(_) => {
            record_method_result(component, refs, SkippableMethod::GetCustomCode, true);
            return Ok(Symbol::EMPTY);
        }
    };
    if v.is_none() {
        record_method_result(component, refs, SkippableMethod::GetCustomCode, true);
        return Ok(Symbol::EMPTY);
    }
    let s = py_str(&v)?;
    if s.is_empty() {
        record_method_result(component, refs, SkippableMethod::GetCustomCode, true);
        Ok(Symbol::EMPTY)
    } else {
        record_method_result(component, refs, SkippableMethod::GetCustomCode, false);
        Ok(intern(&s))
    }
}

/// Read `_get_dynamic_imports()`. Returns `str | None` per-component;
/// the snapshot stores it as a single-element SmallVec for uniformity
/// with the aggregate walk's output shape.
fn read_dynamic_imports<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[Symbol; 1]>, PyReadError> {
    let py = component.py();
    let mut out: SmallVec<[Symbol; 1]> = SmallVec::new();
    // C: skip-list — most classes never override _get_dynamic_imports,
    // so it returns None / "" universally.
    if skip_method(component, refs, SkippableMethod::GetDynamicImports) {
        return Ok(out);
    }
    let v = match refs.call_cached0(component, refs.attrs.m_get_dynamic_imports.bind(py), |c| {
        &mut c.get_dynamic_imports
    }) {
        Ok(v) => v,
        Err(_) => {
            record_method_result(component, refs, SkippableMethod::GetDynamicImports, true);
            return Ok(out);
        }
    };
    if v.is_none() {
        record_method_result(component, refs, SkippableMethod::GetDynamicImports, true);
        return Ok(out);
    }
    if let Ok(s) = py_str(&v) {
        if !s.is_empty() {
            out.push(intern(&s));
            record_method_result(component, refs, SkippableMethod::GetDynamicImports, false);
            return Ok(out);
        }
    }
    if let Ok(iter) = v.iter() {
        for item in iter {
            let s = match item {
                Ok(o) => py_str(&o)?,
                Err(_) => continue,
            };
            if !s.is_empty() {
                out.push(intern(&s));
            }
        }
    }
    record_method_result(
        component,
        refs,
        SkippableMethod::GetDynamicImports,
        out.is_empty(),
    );
    Ok(out)
}

/// Read `get_ref()` → JS ref identifier name, or `Symbol::EMPTY` for None.
fn read_ref_name(component: &Bound<'_, PyAny>) -> Result<Symbol, PyReadError> {
    let v = match component.call_method0("get_ref") {
        Ok(v) => v,
        Err(_) => return Ok(Symbol::EMPTY),
    };
    if v.is_none() {
        return Ok(Symbol::EMPTY);
    }
    let s = py_str(&v)?;
    if s.is_empty() {
        Ok(Symbol::EMPTY)
    } else {
        Ok(intern(&s))
    }
}

/// Read a `dict[str, VarData | None]` hook map. The dict keys are the
/// hook source fragments; values carry the position bucket
/// (`Hooks.HookPosition` — INTERNAL/PRE_TRIGGER/POST_TRIGGER) used for
/// sorting at codegen time.
fn read_hooks_internal<'py, const N: usize>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[HookEntry; N]>, PyReadError>
where
    [HookEntry; N]: smallvec::Array<Item = HookEntry>,
{
    let py = component.py();
    let mut out: SmallVec<[HookEntry; N]> = SmallVec::new();
    let v = match refs.call_cached0(component, refs.attrs.m_get_hooks_internal.bind(py), |c| {
        &mut c.get_hooks_internal
    }) {
        Ok(v) => v,
        Err(_) => return Ok(out),
    };
    if v.is_none() {
        return Ok(out);
    }
    let dict: Bound<'_, PyDict> = match v.downcast_into() {
        Ok(d) => d,
        Err(_) => return Ok(out),
    };
    for (key, val) in dict.iter() {
        let code = py_str(&key)?;
        if code.is_empty() {
            continue;
        }
        let position = read_hook_position(&val).unwrap_or(0);
        out.push(HookEntry::new(intern(&code), position));
    }
    Ok(out)
}

/// User hook buckets: `_get_hooks()` returns a single optional string
/// (an override point on `Component`); `_get_added_hooks()` returns a
/// dict keyed by hook code. Union both into `hooks_user`.
fn read_hooks_user<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[HookEntry; 1]>, PyReadError> {
    let py = component.py();
    let mut out: SmallVec<[HookEntry; 1]> = SmallVec::new();
    // `_get_hooks()` → str | Var | None. C: skip-list.
    if !skip_method(component, refs, SkippableMethod::GetHooks) {
        if let Ok(v) = refs.call_cached0(component, refs.attrs.m_get_hooks.bind(py), |c| {
            &mut c.get_hooks
        }) {
            if v.is_none() {
                record_method_result(component, refs, SkippableMethod::GetHooks, true);
            } else {
                let s = py_str(&v).unwrap_or_default();
                if s.is_empty() {
                    record_method_result(component, refs, SkippableMethod::GetHooks, true);
                } else {
                    out.push(HookEntry::new(intern(&s), 1));
                    record_method_result(component, refs, SkippableMethod::GetHooks, false);
                }
            }
        } else {
            record_method_result(component, refs, SkippableMethod::GetHooks, true);
        }
    }
    // `_get_added_hooks()` → dict[str, VarData | None]. C: skip-list.
    if skip_method(component, refs, SkippableMethod::GetAddedHooks) {
        return Ok(out);
    }
    if let Ok(v) = refs.call_cached0(component, refs.attrs.m_get_added_hooks.bind(py), |c| {
        &mut c.get_added_hooks
    }) {
        if v.is_none() {
            record_method_result(component, refs, SkippableMethod::GetAddedHooks, true);
        } else if let Ok(d) = v.downcast::<PyDict>() {
            let was_empty_before = out.len();
            let mut added_any = false;
            for (k, vd) in d.iter() {
                let code = py_str(&k)?;
                if code.is_empty() {
                    continue;
                }
                added_any = true;
                let position = read_hook_position(&vd).unwrap_or(1);
                out.push(HookEntry::new(intern(&code), position));
            }
            let _ = was_empty_before;
            record_method_result(component, refs, SkippableMethod::GetAddedHooks, !added_any);
        } else {
            record_method_result(component, refs, SkippableMethod::GetAddedHooks, true);
        }
    } else {
        record_method_result(component, refs, SkippableMethod::GetAddedHooks, true);
    }
    Ok(out)
}

/// Extract `VarData.position.value` (a `u8`). `None` for no position
/// constraint — codegen treats it the same as `0` (`INTERNAL`).
fn read_hook_position(vd: &Bound<'_, PyAny>) -> Option<u8> {
    if vd.is_none() {
        return None;
    }
    let pos = vd.getattr("position").ok().filter(|v| !v.is_none())?;
    if let Ok(p) = pos.extract::<u8>() {
        return Some(p);
    }
    if let Ok(v) = pos.getattr("value") {
        return v.extract::<u8>().ok();
    }
    None
}

/// Stage 4: harvest the Component's prop set the same way the legacy
/// `pyo3_reader::read_props` does — `get_props()` (dataclass fields) +
/// identity props (`key`, `id`, `class_name`) + `custom_attrs` entries.
/// Names are stored in snake_case as the Component declares them;
/// `emit_*` applies the snake→camel conversion at emit time so the
/// JSX attribute keys come out as React expects.
fn read_rendered_props(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    builder: &mut SnapshotBuilder,
    reactive_out: &mut bool,
    vars_used_out: &mut SmallVec<[VarDataRef; 4]>,
) -> Result<SmallVec<[(Symbol, Symbol); 4]>, PyReadError> {
    let py = component.py();
    let mut raw_pairs: SmallVec<[(String, Symbol); 4]> = SmallVec::new();

    // ---- Dataclass fields via `Component.get_props()` ------------------
    // B: prop names cached **per class** on the session-scoped
    // ClassMetadata cache. First instance of a class calls
    // `get_props` once and stores the resolved name list; later
    // same-class instances iterate the cached list and skip the
    // `get_props` invocation entirely.
    let prop_names = class_get_prop_names(component, refs)?;
    for (raw, interned_name) in &prop_names {
        // `class_` etc. — legacy strips a trailing `_` (Python
        // keyword escape) when emitting; the value lookup uses
        // the un-stripped attr name.
        let attr_name = raw.strip_suffix('_').unwrap_or(raw).to_owned();
        let value_obj = match component.getattr(interned_name.bind(py)) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if value_obj.is_none() {
            continue;
        }
        if !*reactive_out && var_has_reactive_data(&value_obj, refs)? {
            *reactive_out = true;
        }
        if let Some(r) = register_var_data(&value_obj, builder, refs)? {
            if !vars_used_out.contains(&r) {
                vars_used_out.push(r);
            }
        }
        let expr = render_value_as_js(&value_obj, refs)?;
        if expr.is_empty() {
            continue;
        }
        raw_pairs.push((attr_name, intern(&expr)));
    }

    // ---- Identity props -----------------------------------------------
    // `key` / `id` / `class_name` are renderer-attached on every
    // Component; the legacy emitter always splices these when present.
    for name in ["key", "id", "class_name"] {
        let v = match component.getattr(name) {
            Ok(v) if !v.is_none() => v,
            _ => continue,
        };
        if !*reactive_out && var_has_reactive_data(&v, refs)? {
            *reactive_out = true;
        }
        if let Some(r) = register_var_data(&v, builder, refs)? {
            if !vars_used_out.contains(&r) {
                vars_used_out.push(r);
            }
        }
        let expr = render_value_as_js(&v, refs)?;
        if expr.is_empty() {
            continue;
        }
        raw_pairs.push((name.to_owned(), intern(&expr)));
    }

    // ---- `custom_attrs` extra entries ---------------------------------
    if let Ok(custom) = component.getattr(refs.attrs.custom_attrs.bind(py)) {
        if !custom.is_none() {
            if let Ok(mapping) = custom.downcast::<pyo3::types::PyMapping>() {
                if let Ok(keys) = mapping.keys() {
                    if let Ok(iter) = keys.iter() {
                        for key_res in iter {
                            let key = match key_res {
                                Ok(k) => k,
                                Err(_) => continue,
                            };
                            let name: String = match py_str(&key) {
                                Ok(s) => s,
                                Err(_) => continue,
                            };
                            let val = match mapping.get_item(&key) {
                                Ok(v) => v,
                                Err(_) => continue,
                            };
                            if !*reactive_out && var_has_reactive_data(&val, refs)? {
                                *reactive_out = true;
                            }
                            if let Some(r) = register_var_data(&val, builder, refs)? {
                                if !vars_used_out.contains(&r) {
                                    vars_used_out.push(r);
                                }
                            }
                            let expr = render_value_as_js(&val, refs)?;
                            if expr.is_empty() {
                                continue;
                            }
                            raw_pairs.push((name, intern(&expr)));
                        }
                    }
                }
            }
        }
    }

    // ---- Camelize keys, then return unsorted (sort happens at emit) -----
    // Mirrors `Tag.add_props` camelization. Renames are NOT applied here
    // — they live in `snapshot.rename_props[node_idx]` and the emit pass
    // merges rendered_props + event_callbacks + ref + css into a single
    // sorted list before applying renames, matching legacy's
    // `format_props` (sort) → `_replace_prop_names` (rename) order.
    let mut out: SmallVec<[(Symbol, Symbol); 4]> = SmallVec::with_capacity(raw_pairs.len());
    for (snake, value) in raw_pairs {
        let camel = camelize_prop_name(&snake);
        out.push((intern(&camel), value));
    }

    Ok(out)
}

/// Read `component._rename_props` into a `(old, new)` pair list. Used by
/// the snapshot's `rename_props[node_idx]` slot so the emit pass can
/// apply the rename to the sorted, merged prop list per node.
pub(crate) fn read_rename_props<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[(Symbol, Symbol); 1]>, PyReadError> {
    let py = component.py();
    let mut out: SmallVec<[(Symbol, Symbol); 1]> = SmallVec::new();
    let rename_obj = match component.getattr(refs.attrs.rename_props.bind(py)) {
        Ok(v) if !v.is_none() => v,
        _ => return Ok(out),
    };
    let Ok(d) = rename_obj.downcast::<PyDict>() else {
        return Ok(out);
    };
    if d.is_empty() {
        return Ok(out);
    }
    for (old_obj, new_obj) in d.iter() {
        let Ok(old) = py_str(&old_obj) else { continue };
        let Ok(new) = py_str(&new_obj) else { continue };
        out.push((intern(&old), intern(&new)));
    }
    Ok(out)
}

/// Mirrors `reflex_base.utils.format.to_camel_case(name,
/// treat_hyphens_as_underscores=False)`. Splits on `_`, lowercases the
/// first segment (preserves input case actually), title-cases the rest.
/// Hyphens are passed through unchanged so `custom_attrs` keys like
/// `"data-foo"` stay as the user wrote them.
fn camelize_prop_name(name: &str) -> String {
    if !name.contains('_') {
        return name.to_owned();
    }
    let mut out = String::with_capacity(name.len());
    let mut iter = name.split('_');
    if let Some(first) = iter.next() {
        out.push_str(first);
    }
    for word in iter {
        let mut chars = word.chars();
        if let Some(c) = chars.next() {
            out.extend(c.to_uppercase());
            out.extend(chars);
        }
    }
    out
}

/// Stage 4: walk `component.event_triggers` and render each handler to
/// `(snake_trigger, js_expr)`. Trigger names stay snake-cased to match
/// the legacy `fix_event_triggers_for_memo` memo-name convention
/// (`on_click_<hash>`). The emit-time sort camelizes on the fly so the
/// JSX prop key comes out as `onClick`. Skips `on_mount`/`on_unmount`
/// (those become useEffect hooks, not JSX props). Drops the
/// `EVENT_ARG` shape — `LiteralVar.create(handler)._js_expr` handles
/// serialization.
fn read_event_callbacks(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<SmallVec<[(Symbol, Symbol); 2]>, PyReadError> {
    let py = component.py();
    let mut out: SmallVec<[(Symbol, Symbol); 2]> = SmallVec::new();
    let triggers = match component.getattr(refs.attrs.event_triggers.bind(py)) {
        Ok(t) if !t.is_none() => t,
        _ => return Ok(out),
    };
    let Ok(triggers_dict) = triggers.downcast::<PyDict>() else {
        return Ok(out);
    };
    for (trigger_obj, handler_obj) in triggers_dict.iter() {
        let trigger = py_str(&trigger_obj)?;
        if trigger == "on_mount" || trigger == "on_unmount" {
            continue;
        }
        let expr = render_value_as_js(&handler_obj, refs)?;
        if expr.is_empty() {
            continue;
        }
        out.push((intern(&trigger), intern(&expr)));
    }
    Ok(out)
}

/// Stage 4: render `component._get_style()` to a single interned JS
/// expression. Reflex's `_get_style()` returns either `{}` (no style)
/// or `{"css": <Var of pre-rendered emotion JS>}` — extract the Var's
/// `_js_expr` so codegen can splice it as a `style={...}` prop.
fn read_style(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<Symbol, PyReadError> {
    let py = component.py();
    let style_obj = match refs.call_cached0(component, refs.attrs.m_get_style.bind(py), |c| {
        &mut c.get_style
    }) {
        Ok(s) => s,
        Err(_) => return Ok(Symbol::EMPTY),
    };
    if style_obj.is_none() {
        return Ok(Symbol::EMPTY);
    }
    // `_get_style()` returns `dict[str, Var | str | None]`. Normalize to
    // the `{"css": <expr>}` shape produced by the legacy renderer.
    let Ok(d) = style_obj.downcast::<PyDict>() else {
        return Ok(Symbol::EMPTY);
    };
    if d.is_empty() {
        return Ok(Symbol::EMPTY);
    }
    let css_val = match d.get_item("css").ok().flatten() {
        Some(v) if !v.is_none() => v,
        _ => return Ok(Symbol::EMPTY),
    };
    let expr = render_value_as_js(&css_val, refs)?;
    if expr.is_empty() {
        Ok(Symbol::EMPTY)
    } else {
        Ok(intern(&expr))
    }
}

/// PR7: register a Var's `_get_all_var_data()` result in
/// `Snapshot.var_data`, deduplicated by `id(var)`. Returns `Some(idx)`
/// pointing at the entry (existing or freshly inserted) when the Var
/// carries non-trivial metadata; `None` for non-Vars, empty var_data,
/// or var_data that's all-empty buckets.
///
/// The dense backings (`var_hooks`, `var_imports`, `var_deps`,
/// `var_components`) are appended in observation order; each new
/// entry owns a `Range<u32>` slice. This matches the layout the plan's
/// "Var-data dedup table" §PR7 describes.
fn register_var_data(
    value: &Bound<'_, PyAny>,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'_>,
) -> Result<Option<VarDataRef>, PyReadError> {
    let is_var = match value.is_instance(&refs.var_cls) {
        Ok(b) => b,
        Err(_) => return Ok(None),
    };
    if !is_var {
        return Ok(None);
    }
    let key = value.as_ptr() as usize;
    if let Some(idx) = refs.var_data_dedup.borrow().get(&key) {
        return Ok(Some(VarDataRef(*idx)));
    }
    let py = value.py();
    let var_data = match refs.call_cached0(value, refs.attrs.m_get_all_var_data.bind(py), |c| {
        &mut c.get_all_var_data
    }) {
        Ok(v) => v,
        Err(_) => return Ok(None),
    };
    if var_data.is_none() {
        return Ok(None);
    }

    // Pull each bucket eagerly into Rust-side Vec<Symbol> first; only
    // commit to `snapshot.var_data` if at least one bucket is
    // non-empty (matches `var_has_reactive_data`'s definition of
    // "carries metadata worth deduping"). Pure-static pages then end
    // up with `var_data_len == 0`.
    let hooks_syms = pull_dict_keys(&var_data, "hooks");
    let imports_pairs = pull_imports(&var_data, refs);
    let deps_syms = pull_iter_symbols(&var_data, "deps");
    let components_syms = pull_iter_symbols(&var_data, "components");
    let state_sym = pull_state_symbol(&var_data, refs);
    let position = pull_u8(&var_data, "position");

    let any_nontrivial = !hooks_syms.is_empty()
        || !imports_pairs.is_empty()
        || !deps_syms.is_empty()
        || !components_syms.is_empty()
        || state_sym != Symbol::EMPTY;
    if !any_nontrivial {
        return Ok(None);
    }

    let snap = builder.snapshot_mut();
    let hooks_start = snap.var_hooks.len() as u32;
    snap.var_hooks.extend(hooks_syms);
    let hooks_end = snap.var_hooks.len() as u32;
    let imports_start = snap.var_imports.len() as u32;
    snap.var_imports.extend(imports_pairs);
    let imports_end = snap.var_imports.len() as u32;
    let deps_start = snap.var_deps.len() as u32;
    snap.var_deps.extend(deps_syms);
    let deps_end = snap.var_deps.len() as u32;
    let comps_start = snap.var_components.len() as u32;
    snap.var_components.extend(components_syms);
    let comps_end = snap.var_components.len() as u32;

    let entry = VarDataEntry {
        hooks: hooks_start..hooks_end,
        imports: imports_start..imports_end,
        deps: deps_start..deps_end,
        components: comps_start..comps_end,
        state: state_sym,
        position: position.unwrap_or(u8::MAX),
    };
    let idx = snap.var_data.len() as u32;
    snap.var_data.push(entry);
    refs.var_data_dedup.borrow_mut().insert(key, idx);
    Ok(Some(VarDataRef(idx)))
}

fn pull_dict_keys(var_data: &Bound<'_, PyAny>, attr: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    if let Ok(obj) = var_data.getattr(attr) {
        if !obj.is_none() {
            if let Ok(keys_iter) = obj.iter() {
                for k in keys_iter.flatten() {
                    if let Ok(s) = py_str(&k) {
                        out.push(intern(&s));
                    }
                }
            }
        }
    }
    out
}

fn pull_imports<'py>(var_data: &Bound<'py, PyAny>, refs: &PyRefs<'py>) -> Vec<(Symbol, Symbol)> {
    let py = var_data.py();
    let mut out = Vec::new();
    let Ok(obj) = var_data.getattr(refs.attrs.imports.bind(py)) else {
        return out;
    };
    if obj.is_none() {
        return out;
    }
    // `imports` is a mapping `{module: [ImportVar, ...]}` per
    // `reflex_base.vars.base.VarData`. Mirror the JSX-block summary:
    // one `(module, name)` pair per ImportVar where `name` falls back
    // to alias/tag.
    if let Ok(keys_iter) = obj.call_method0("items") {
        if let Ok(it) = keys_iter.iter() {
            for kv in it.flatten() {
                let Ok(tup) = kv.downcast::<pyo3::types::PyTuple>() else {
                    continue;
                };
                if tup.len() != 2 {
                    continue;
                }
                let Ok(module_obj) = tup.get_item(0) else {
                    continue;
                };
                let Ok(module) = py_str(&module_obj) else {
                    continue;
                };
                let Ok(items) = tup.get_item(1) else { continue };
                if items.is_none() {
                    continue;
                }
                if let Ok(items_iter) = items.iter() {
                    for iv in items_iter.flatten() {
                        let name = iv
                            .getattr(refs.attrs.tag.bind(py))
                            .ok()
                            .filter(|v| !v.is_none())
                            .and_then(|v| py_str(&v).ok())
                            .or_else(|| {
                                iv.getattr(refs.attrs.alias.bind(py))
                                    .ok()
                                    .filter(|v| !v.is_none())
                                    .and_then(|v| py_str(&v).ok())
                            });
                        if let Some(n) = name {
                            out.push((intern(&module), intern(&n)));
                        }
                    }
                }
            }
        }
    }
    out
}

fn pull_iter_symbols(var_data: &Bound<'_, PyAny>, attr: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    if let Ok(obj) = var_data.getattr(attr) {
        if !obj.is_none() {
            if let Ok(it) = obj.iter() {
                for v in it.flatten() {
                    if let Ok(s) = py_str(&v) {
                        if !s.is_empty() {
                            out.push(intern(&s));
                        }
                    }
                }
            }
        }
    }
    out
}

fn pull_state_symbol<'py>(var_data: &Bound<'py, PyAny>, refs: &PyRefs<'py>) -> Symbol {
    let py = var_data.py();
    let Ok(obj) = var_data.getattr(refs.attrs.state.bind(py)) else {
        return Symbol::EMPTY;
    };
    if obj.is_none() {
        return Symbol::EMPTY;
    }
    let Ok(s) = py_str(&obj) else {
        return Symbol::EMPTY;
    };
    if s.is_empty() {
        Symbol::EMPTY
    } else {
        intern(&s)
    }
}

fn pull_u8(var_data: &Bound<'_, PyAny>, attr: &str) -> Option<u8> {
    let obj = var_data.getattr(attr).ok().filter(|v| !v.is_none())?;
    if let Ok(p) = obj.extract::<u8>() {
        return Some(p);
    }
    obj.getattr("value")
        .ok()
        .and_then(|v| v.extract::<u8>().ok())
}

/// Check whether `value` is a `Var` whose `_get_all_var_data()` carries
/// reactive state, hooks, or embedded reactive components.
///
/// PR2: this is the per-prop / per-Bare-contents check that makes
/// `should_memoize_arena` accurate against the Python predicate. Mirrors
/// the per-Var loop in `_should_memoize` (memoize.py:174–182). Called
/// from `read_rendered_props` once per prop Var the freeze already
/// touches, and from the Bare-contents branch below.
///
/// Returns `true` when:
///
/// * `var_data.state` is non-empty (the Var reads from a state class)
/// * `var_data.hooks` is non-empty (the Var introduces a React hook)
/// * Any `var_data.components` entry has reactive descendants
///   (recursive `_subtree_has_reactive_data` check)
///
/// `_get_all_var_data` is `@functools.cache`-decorated on the Var class,
/// so repeated calls for the same Var are sub-µs after the first.
fn var_has_reactive_data(value: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<bool, PyReadError> {
    let is_var = match value.is_instance(&refs.var_cls) {
        Ok(b) => b,
        Err(_) => return Ok(false),
    };
    if !is_var {
        return Ok(false);
    }
    let py = value.py();
    let var_data = match refs.call_cached0(value, refs.attrs.m_get_all_var_data.bind(py), |c| {
        &mut c.get_all_var_data
    }) {
        Ok(v) => v,
        Err(_) => return Ok(false),
    };
    if var_data.is_none() {
        return Ok(false);
    }
    // `state` is a string (state class identifier or ""); non-empty
    // means reactive.
    if let Ok(state) = var_data.getattr(refs.attrs.state.bind(py)) {
        if !state.is_none() {
            if let Ok(s) = py_str(&state) {
                if !s.is_empty() {
                    return Ok(true);
                }
            }
        }
    }
    // `hooks` is a dict-like; non-empty means reactive.
    if let Ok(hooks) = var_data.getattr(refs.attrs.hooks.bind(py)) {
        if !hooks.is_none() {
            let is_empty = hooks
                .call_method0("__len__")
                .ok()
                .and_then(|n| n.extract::<usize>().ok())
                .map(|n| n == 0)
                .unwrap_or(true);
            if !is_empty {
                return Ok(true);
            }
        }
    }
    // `components` is a sequence of Component instances embedded in
    // the Var's value. Recurse into each; their reactivity bubbles via
    // `_subtree_has_reactive_data` in Python. We mirror that with a
    // bounded depth-first check on each embedded component.
    if let Ok(components) = var_data.getattr(refs.attrs.components.bind(py)) {
        if !components.is_none() {
            if let Ok(iter) = components.iter() {
                for c_res in iter {
                    let c = match c_res {
                        Ok(o) => o,
                        Err(_) => continue,
                    };
                    if subtree_has_reactive_data(&c, refs, 0)? {
                        return Ok(true);
                    }
                }
            }
        }
    }
    Ok(false)
}

/// Mirror `reflex.compiler.plugins.memoize._subtree_has_reactive_data`
/// for a Component instance embedded inside a Var's `var_data.components`.
///
/// Used only by `var_has_reactive_data` — the embedded-Component case
/// the page tree walk doesn't otherwise visit. Bounded by a recursion
/// depth cap so a pathological circular embedding doesn't blow the
/// stack; in practice user code never nests deeper than ~5.
fn subtree_has_reactive_data<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
    depth: u8,
) -> Result<bool, PyReadError> {
    let py = component.py();
    if depth > 8 {
        return Ok(false);
    }
    // Check the component's own prop Vars and event triggers.
    if let Ok(vars_iter) = component.call_method1("_get_vars", (false,)) {
        if let Ok(iter) = vars_iter.iter() {
            for v_res in iter {
                let v = match v_res {
                    Ok(o) => o,
                    Err(_) => continue,
                };
                if var_has_reactive_data(&v, refs)? {
                    return Ok(true);
                }
            }
        }
    }
    if let Ok(triggers) = component.getattr(refs.attrs.event_triggers.bind(py)) {
        let is_empty = triggers
            .call_method0("__len__")
            .ok()
            .and_then(|n| n.extract::<usize>().ok())
            .map(|n| n == 0)
            .unwrap_or(true);
        if !is_empty {
            return Ok(true);
        }
    }
    // Recurse into children.
    if let Ok(children) = component.getattr(refs.attrs.children.bind(py)) {
        if let Ok(iter) = children.iter() {
            for c_res in iter {
                let c = match c_res {
                    Ok(o) => o,
                    Err(_) => continue,
                };
                if subtree_has_reactive_data(&c, refs, depth + 1)? {
                    return Ok(true);
                }
            }
        }
    }
    Ok(false)
}

/// Render any Python value into its JS expression form via
/// `LiteralVar.create(v)._js_expr`. Already-`Var` values short-circuit
/// to their own `_js_expr`. Primitive Python values (`bool`/`int`/
/// `float`/`str`/`None`) take a Rust-only fast path so the freeze
/// pass avoids the `LiteralVar.create` round-trip on the common case
/// — that single PyO3 method call costs ~50 µs and fires once per
/// non-Var prop value (and once per non-Var event handler), which on
/// a typical page adds up to 3–5 ms of pure boundary overhead.
fn render_value_as_js<'py>(
    value: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<String, PyReadError> {
    let py = value.py();
    if value.is_none() {
        return Ok(String::new());
    }
    let is_var = value
        .is_instance(&refs.var_cls)
        .map_err(|source| PyReadError::Attr {
            attr: "isinstance(value, Var)",
            source,
        })?;
    if is_var {
        let expr = value
            .getattr(refs.attrs.js_expr.bind(py))
            .map_err(|source| PyReadError::Attr {
                attr: "Var._js_expr",
                source,
            })?;
        return py_str(&expr);
    }

    // Primitive fast paths: bool BEFORE int (Python bool is a subclass
    // of int and would match `extract::<i64>` first). Strings get JSON-
    // encoded the same way `LiteralVar.create(s)._js_expr` would.
    if let Ok(b) = value.extract::<bool>() {
        // `extract::<bool>()` accepts ints too in older pyo3 versions;
        // gate on the real `bool` type so we don't misclassify 0/1.
        if value.is_instance_of::<pyo3::types::PyBool>() {
            return Ok(if b {
                "true".to_owned()
            } else {
                "false".to_owned()
            });
        }
    }
    if value.is_instance_of::<pyo3::types::PyInt>() {
        if let Ok(n) = value.extract::<i64>() {
            return Ok(n.to_string());
        }
    }
    if value.is_instance_of::<pyo3::types::PyFloat>() {
        if let Ok(f) = value.extract::<f64>() {
            return Ok(format_js_float(f));
        }
    }
    if value.is_instance_of::<pyo3::types::PyString>() {
        if let Ok(s) = value.extract::<String>() {
            return Ok(encode_js_string(&s));
        }
    }

    // Wrap arbitrary Python values into a Var via `LiteralVar.create`.
    // Mappings / EventChain / lists-of-Vars all go through this path.
    let wrapped = refs
        .literal_var_cls
        .call_method1("create", (value,))
        .map_err(|source| PyReadError::Attr {
            attr: "LiteralVar.create(value)",
            source,
        })?;
    if wrapped.is_none() {
        return Ok(String::new());
    }
    // Wrapped value is normally a Var; pull its `_js_expr`.
    if let Ok(expr) = wrapped.getattr(refs.attrs.js_expr.bind(py)) {
        return py_str(&expr);
    }
    // Last-ditch: stringify.
    py_str(&wrapped)
}

/// Strip a trailing `@<version>` from a library specifier. Mirrors
/// `reflex_base.utils.format.format_library_name`:
/// - URLs (`https://…`) pass through unchanged.
/// - `@scope/pkg@1.2.3` → `@scope/pkg`.
/// - `pkg@1.2.3` → `pkg`.
/// - `@scope/pkg` (no trailing version) → `@scope/pkg`.
/// - `pkg` → `pkg`.
fn format_library_name_str(lib: &str) -> &str {
    if lib.starts_with("https://") {
        return lib;
    }
    match lib.rsplit_once('@') {
        Some((head, _version)) if !head.is_empty() => head,
        _ => lib,
    }
}

/// JSON-encode a string the same way `LiteralVar.create(s)._js_expr` does:
/// wrap in double quotes, escape `"`, `\`, control chars (`\n`/`\t`/`\r`/
/// `\b`/`\f`), and `\uXXXX`-escape any non-ASCII code point. Matches
/// `json.dumps(s, ensure_ascii=True)` byte-for-byte.
fn encode_js_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{000C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c if (c as u32) < 0x7F => out.push(c),
            c => {
                // ensure_ascii=True: non-ASCII becomes `\uXXXX` (or a
                // surrogate pair for code points beyond the BMP).
                let cp = c as u32;
                if cp <= 0xFFFF {
                    out.push_str(&format!("\\u{:04x}", cp));
                } else {
                    let cp = cp - 0x10000;
                    let high = 0xD800 + (cp >> 10);
                    let low = 0xDC00 + (cp & 0x3FF);
                    out.push_str(&format!("\\u{high:04x}\\u{low:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

/// Format a Python float the same way `LiteralVar.create(f)._js_expr`
/// (which delegates to `repr`) does. The common case for finite floats is
/// `repr` + JS-compatible — `3.14`, `1e20`, etc.
fn format_js_float(f: f64) -> String {
    if f.is_nan() {
        return "NaN".to_owned();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity" } else { "-Infinity" }.to_owned();
    }
    // Python `repr` of a float that's exactly an integer prints with
    // `.0` (e.g. `repr(1.0) == '1.0'`); the default Rust `format!` does
    // the same. For the rest, Rust's f64 Display matches Python repr in
    // the overwhelming common case (both use the shortest round-trip).
    if f.fract() == 0.0 && f.is_finite() && f.abs() < 1e16 {
        return format!("{f:.1}");
    }
    format!("{f}")
}

#[cfg(test)]
mod render_value_primitive_tests {
    use super::{encode_js_string, format_js_float, format_library_name_str};

    #[test]
    fn format_library_name_strips_version() {
        assert_eq!(
            format_library_name_str("@radix-ui/themes@3.3.0"),
            "@radix-ui/themes"
        );
        assert_eq!(format_library_name_str("react@18.2.0"), "react");
        assert_eq!(format_library_name_str("react"), "react");
        assert_eq!(
            format_library_name_str("@radix-ui/themes"),
            "@radix-ui/themes"
        );
        assert_eq!(
            format_library_name_str("https://cdn.example/x@1"),
            "https://cdn.example/x@1"
        );
        assert_eq!(format_library_name_str(""), "");
    }

    #[test]
    fn encode_js_string_basics() {
        assert_eq!(encode_js_string("hello"), "\"hello\"");
        assert_eq!(encode_js_string(""), "\"\"");
    }

    #[test]
    fn encode_js_string_escapes() {
        assert_eq!(encode_js_string("a\"b"), "\"a\\\"b\"");
        assert_eq!(encode_js_string("a\\b"), "\"a\\\\b\"");
        assert_eq!(encode_js_string("a\nb"), "\"a\\nb\"");
        assert_eq!(encode_js_string("a\tb"), "\"a\\tb\"");
    }

    #[test]
    fn encode_js_string_non_ascii() {
        assert_eq!(encode_js_string("é"), "\"\\u00e9\"");
        // Beyond BMP: encoded as surrogate pair.
        assert_eq!(encode_js_string("😀"), "\"\\ud83d\\ude00\"");
    }

    #[test]
    fn format_js_float_round_numbers() {
        assert_eq!(format_js_float(1.0), "1.0");
        assert_eq!(format_js_float(3.14), "3.14");
        assert_eq!(format_js_float(-0.5), "-0.5");
    }
}

/// Populate `snapshot.control_flow` for kinds that carry sparse
/// side-table data (Text content, Expr value, Cond.test, Foreach.iter,
/// Match.value, Memoize.key). Match arms (case → body index) are
/// deferred to a follow-on Stage 5 sub-task because they need
/// per-arm pairing with the just-pushed child indices.
fn populate_control_flow<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    kind: NodeKind,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
) -> Result<(), PyReadError> {
    match kind {
        NodeKind::Text => {
            // `Bare.contents` may be a non-Var Python value (plain string)
            // OR a Var whose `_js_expr` is a quoted-string literal
            // (`classify_bare` routes those to `Text`). The literal-Var
            // case needs decoding from the `"…"` JS form to the raw
            // text — otherwise the emit would write the escape sequence
            // verbatim instead of the glyph (e.g. `"−"` vs `"−"`).
            if let Ok(contents) = component.getattr(refs.attrs.contents.bind(py)) {
                if !contents.is_none() {
                    let is_var = contents.is_instance(&refs.var_cls).unwrap_or(false);
                    let s = if is_var {
                        contents
                            .getattr(refs.attrs.js_expr.bind(py))
                            .ok()
                            .and_then(|e| py_str(&e).ok())
                            .and_then(|expr| crate::text::decode_js_string_literal(&expr))
                            .unwrap_or_default()
                    } else {
                        py_str(&contents).unwrap_or_default()
                    };
                    if !s.is_empty() {
                        builder
                            .snapshot_mut()
                            .control_flow
                            .text_value
                            .insert(self_idx, intern(&s));
                    }
                }
            }
        }
        NodeKind::Expr => {
            // The Bare wraps a `Var` whose `_js_expr` is the inline
            // expression.  Re-extract the var here (matches the
            // classification step's instance check).
            if let Ok(contents) = component.getattr(refs.attrs.contents.bind(py)) {
                if !contents.is_none() {
                    let expr = render_value_as_js(&contents, refs)?;
                    if !expr.is_empty() {
                        builder
                            .snapshot_mut()
                            .control_flow
                            .expr_value
                            .insert(self_idx, intern(&expr));
                    }
                }
            }
        }
        NodeKind::Cond => {
            if let Ok(cond) = component.getattr(refs.attrs.cond.bind(py)) {
                let expr = render_value_as_js(&cond, refs)?;
                if !expr.is_empty() {
                    builder
                        .snapshot_mut()
                        .control_flow
                        .cond_test
                        .insert(self_idx, intern(&expr));
                }
            }
        }
        NodeKind::Foreach => {
            if let Ok(iterable) = component.getattr(refs.attrs.iterable.bind(py)) {
                let expr = render_value_as_js(&iterable, refs)?;
                if !expr.is_empty() {
                    builder
                        .snapshot_mut()
                        .control_flow
                        .foreach_iter
                        .insert(self_idx, intern(&expr));
                }
            }
        }
        NodeKind::Match => {
            if let Ok(cond) = component.getattr(refs.attrs.cond.bind(py)) {
                let expr = render_value_as_js(&cond, refs)?;
                if !expr.is_empty() {
                    builder
                        .snapshot_mut()
                        .control_flow
                        .match_value
                        .insert(self_idx, intern(&expr));
                }
            }
        }
        NodeKind::Memoize => {
            // Memoize wrappers carry a React `key=` value. Today the
            // freeze pass doesn't see live Memoize Components (memoize
            // substitution runs after freeze in the pipeline), so this
            // branch is reserved for Stage 6 once the arena memoize
            // pass starts inserting `MemoizeWrapper` nodes.
        }
        _ => {}
    }
    Ok(())
}

/// Recurse into the kind-appropriate child set and return the
/// `(children_start, children_end)` slice the parent should record in
/// its `NodeSnapshot.children` field. The returned range covers
/// exactly the direct children's slots; descendants land past
/// `children_end` in the arena.
fn freeze_children_for<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    kind: NodeKind,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(NodeIdx, NodeIdx), PyReadError> {
    match kind {
        NodeKind::Foreach => freeze_foreach_body(py, component, builder, refs, pending),
        NodeKind::Match => freeze_match_children(py, component, self_idx, builder, refs, pending),
        _ => freeze_children_iter(py, component, builder, refs, pending),
    }
}

/// `Element`, `Fragment`, `Cond`, `Memoize`, `MemoizeWrapper`: iterate the
/// `children` attribute. `Cond.children` is `[then, else]`; `Memoize.children`
/// is a single body; both fit the same shape.
fn freeze_children_iter<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(NodeIdx, NodeIdx), PyReadError> {
    let start = builder.next_idx();
    let children_obj = match component.getattr(refs.attrs.children.bind(py)) {
        Ok(v) if !v.is_none() => v,
        _ => return Ok((start, start)),
    };
    // Materialize the child PyObjects so we can pre-reserve sibling
    // slots before recursing into any one of them.
    let children: Vec<Bound<'py, PyAny>> = children_obj
        .iter()
        .map_err(|source| PyReadError::Attr {
            attr: "iter(component.children)",
            source,
        })?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| PyReadError::Attr {
            attr: "component.children[i]",
            source,
        })?;
    let mut child_slots: Vec<NodeIdx> = Vec::with_capacity(children.len());
    for _ in 0..children.len() {
        child_slots.push(builder.reserve());
    }
    let end = builder.next_idx();
    for (slot, child) in child_slots.into_iter().zip(children.into_iter()) {
        freeze_into_slot(py, &child, slot, builder, refs, pending)?;
    }
    Ok((start, end))
}

/// `Foreach`: the body subtree is recovered via
/// `component._render().render_component()`. Mirrors `read_foreach` in
/// `pyo3_reader.rs` — `_render()` constructs an `IterTag` whose
/// `render_component()` returns the body's `Component` with the iter-var
/// properly typed.
fn freeze_foreach_body<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(NodeIdx, NodeIdx), PyReadError> {
    let iter_tag = component
        .call_method0("_render")
        .map_err(|source| PyReadError::Attr {
            attr: "Foreach._render()",
            source,
        })?;
    let body = iter_tag
        .call_method0("render_component")
        .map_err(|source| PyReadError::Attr {
            attr: "IterTag.render_component()",
            source,
        })?;
    let start = builder.reserve();
    let end = builder.next_idx();
    freeze_into_slot(py, &body, start, builder, refs, pending)?;
    Ok((start, end))
}

/// `Match`: walk each entry of `match_cases` (`[case_a, …, body]`) plus
/// the optional `default` body. Records each `(case_expr → body_idx)`
/// pairing into `snapshot.control_flow.match_arms` and the default into
/// `match_default` so `emit_jsx_from_snapshot` can render the arms.
fn freeze_match_children<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(NodeIdx, NodeIdx), PyReadError> {
    let start = builder.next_idx();
    let mut arms: SmallVec<[(Symbol, NodeIdx); 2]> = SmallVec::new();
    if let Ok(cases) = component.getattr("match_cases") {
        if !cases.is_none() {
            let cases_list: Bound<'_, PyList> =
                cases
                    .downcast_into()
                    .map_err(|e| PyReadError::TypeMismatch {
                        attr: "Match.match_cases",
                        expected: "list",
                        got: e.to_string(),
                    })?;
            for entry in cases_list.iter() {
                let entries: Vec<Bound<'_, PyAny>> = entry
                    .iter()
                    .map_err(|source| PyReadError::Attr {
                        attr: "iter(Match case entry)",
                        source,
                    })?
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|source| PyReadError::Attr {
                        attr: "Match case entry[i]",
                        source,
                    })?;
                if entries.len() < 2 {
                    continue;
                }
                let body = entries.last().expect("len >= 2");
                let body_idx = freeze_node(py, body, builder, refs, pending)?;
                for case_obj in &entries[..entries.len() - 1] {
                    let case_expr = render_value_as_js(case_obj, refs)?;
                    let case_sym = if case_expr.is_empty() {
                        intern("null")
                    } else {
                        intern(&case_expr)
                    };
                    arms.push((case_sym, body_idx));
                }
            }
        }
    }
    if !arms.is_empty() {
        builder
            .snapshot_mut()
            .control_flow
            .match_arms
            .insert(self_idx, arms);
    }
    if let Ok(default) = component.getattr("default") {
        if !default.is_none() {
            let default_idx = freeze_node(py, &default, builder, refs, pending)?;
            builder
                .snapshot_mut()
                .control_flow
                .match_default
                .insert(self_idx, default_idx);
        }
    }
    // Match has no structural children — arm bodies live in
    // `control_flow.match_arms` / `match_default`. The node's own
    // `children` range stays empty so iterating it from the JSX emit
    // is a no-op.
    let _ = start;
    let end = builder.next_idx();
    Ok((end, end))
}

/// Discriminate the node kind by class name plus, for `Bare`, an
/// `isinstance(contents, Var)` check. Stage 0 only distinguishes the
/// structural kinds; `MemoizeWrapper` / `Memoize` are emitted later by
/// the in-arena memoize pass.
fn classify(
    component: &Bound<'_, PyAny>,
    cls: &str,
    refs: &PyRefs<'_>,
) -> Result<(NodeKind, Symbol), PyReadError> {
    let kind = match cls {
        "Bare" => classify_bare(component, refs)?,
        "Fragment" => NodeKind::Fragment,
        "Cond" => NodeKind::Cond,
        "Foreach" => NodeKind::Foreach,
        "Match" => NodeKind::Match,
        _ => NodeKind::Element,
    };
    let tag = if matches!(kind, NodeKind::Element) {
        read_tag(component, refs)?
    } else {
        Symbol::EMPTY
    };
    Ok((kind, tag))
}

/// `Bare` with `Var` contents emits as `Expr` (inline JSX expression);
/// otherwise it's plain `Text`. Vars whose `_js_expr` is a quoted
/// string literal (e.g. `"−"`) get decoded to Text so the output
/// is the raw glyph instead of the escape sequence — mirrors
/// `pyo3_reader::read_bare`'s `decode_js_string_literal` step.
fn classify_bare<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<NodeKind, PyReadError> {
    let py = component.py();
    let contents = match component.getattr(refs.attrs.contents.bind(py)) {
        Ok(v) if !v.is_none() => v,
        _ => return Ok(NodeKind::Text),
    };
    let is_var = contents
        .is_instance(&refs.var_cls)
        .map_err(|source| PyReadError::Attr {
            attr: "isinstance(Bare.contents, Var)",
            source,
        })?;
    if !is_var {
        return Ok(NodeKind::Text);
    }
    // Var contents whose JS form is `"..."` — a literal — decodes to
    // the inner text and emits as Text. Anything else stays as Expr.
    if let Ok(expr_obj) = contents.getattr(refs.attrs.js_expr.bind(py)) {
        let expr_str = py_str(&expr_obj).unwrap_or_default();
        if crate::text::decode_js_string_literal(&expr_str).is_some() {
            return Ok(NodeKind::Text);
        }
    }
    Ok(NodeKind::Expr)
}

/// Mirror `resolve_tag_symbol` in `pyo3_reader.rs`: prefer
/// `component.alias` over `component.tag`, strip surrounding quotes,
/// then re-wrap in quotes when the tag is a global-scope HTML element
/// (no library set + `_is_tag_in_global_scope` truthy) — e.g.
/// `"title"`, `"meta"`, `"div"`. The emit treats `"…"` symbols as
/// pre-quoted tag literals.
fn read_tag(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<Symbol, PyReadError> {
    let py = component.py();
    let alias = component
        .getattr(refs.attrs.alias.bind(py))
        .ok()
        .filter(|v| !v.is_none());
    let tag = component
        .getattr(refs.attrs.tag.bind(py))
        .ok()
        .filter(|v| !v.is_none());
    let raw_name = match (alias, tag) {
        (Some(a), _) => py_str(&a)?,
        (None, Some(t)) => py_str(&t)?,
        _ => return Ok(Symbol::EMPTY),
    };
    let trimmed = raw_name.trim_matches('"').to_owned();
    if trimmed.is_empty() {
        return Ok(Symbol::EMPTY);
    }
    let library = component
        .getattr(refs.attrs.library.bind(py))
        .ok()
        .filter(|v| !v.is_none());
    let is_global_scope = match component.getattr(refs.attrs.is_tag_in_global_scope.bind(py)) {
        Ok(v) => v.is_truthy().unwrap_or(false),
        Err(_) => false,
    };
    let final_name = if library.is_none() && is_global_scope {
        format!("\"{trimmed}\"")
    } else {
        trimmed
    };
    Ok(intern(&final_name))
}

/// `type(component).__qualname__`. Used as the `style_key` so stage 5's
/// app-style merge can look up `App.style[<qualname>]` for each node.
fn read_qualname<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Symbol, PyReadError> {
    let py = component.py();
    let ty = component.get_type();
    if let Ok(q) = ty.getattr(refs.attrs.qualname.bind(py)) {
        if let Ok(s) = py_str(&q) {
            return Ok(intern(&s));
        }
    }
    // Fallback: class __name__. Matches `class_name()` used elsewhere.
    let name = ty.name().map_err(|source| PyReadError::Attr {
        attr: "type(component).__name__",
        source,
    })?;
    Ok(intern(&name.to_string()))
}

#[cfg(test)]
mod node_kind_tests {
    use super::*;

    #[test]
    fn read_qualname_helper_compiles() {
        // Smoke test that `read_qualname` is referenced from another
        // call site (the integration test in tests/freeze_smoke.rs
        // exercises it under a real PyO3 component). Signature now
        // takes a `&PyRefs` after PR-Freeze-Speedup-B threaded the
        // interned attr names through this helper.
        let _ = read_qualname
            as for<'a, 'py, 'b> fn(
                &'a Bound<'py, PyAny>,
                &'b PyRefs<'py>,
            ) -> Result<Symbol, PyReadError>;
    }
}
