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
use reflex_vars::RustVar;

use crate::pyo3_reader::{
    class_name, instance_dict, py_str, read_field, MemoModeCached, PyReadError, PyRefs,
    SkippableMethod, REVALIDATE_EVERY_N, TRIVIAL_WARMUP_THRESHOLD,
};
use crate::timing::{self, Counter as TC, Field as TF, Span as TSpan};

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

/// Full-port: read a Var as its native `RustVar` struct when safe.
///
/// After the Var cutover the JS expression and the whole `VarData` tree
/// live in Rust memory — going through `getattr("_js_expr")` /
/// `_get_all_var_data()` pays the Python attribute protocol, a getter
/// call, a `VarData` clone, and string round-trips for data we already
/// own. Eligibility is cached per class: exact `RustVar`, or a subclass
/// whose `_js_expr` and `_get_all_var_data` descriptors are identical to
/// the base ones (a Python override keeps the generic path).
fn native_var<'a>(value: &'a Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Option<&'a RustVar> {
    let bound = value.downcast::<RustVar>().ok()?;
    let safe = class_bool_flag(
        value,
        refs,
        |m| m.rustvar_direct,
        |m, v| m.rustvar_direct = Some(v),
        || {
            let ty = value.get_type();
            if ty.is(&refs.rustvar_type) {
                return true;
            }
            ty.getattr("_js_expr")
                .map(|d| d.is(&refs.rustvar_js_expr_desc))
                .unwrap_or(false)
                && ty
                    .getattr("_get_all_var_data")
                    .map(|d| d.is(&refs.rustvar_gavd_desc))
                    .unwrap_or(false)
        },
    );
    if safe {
        Some(bound.get())
    } else {
        None
    }
}

/// M2 deferred style fold: whether `component` carries the
/// `_style_fold_root` instance mark, set by
/// `compile_unevaluated_page(apply_style=False)` on the exact subtree the
/// legacy `_add_style_recursive` would have walked. Probed only while the
/// fold is inactive, and only when the caller supplied an `App.style`.
fn style_fold_mark_present(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> bool {
    if refs.style_fold_style.borrow().is_none() {
        return false;
    }
    let py = component.py();
    crate::pyo3_reader::instance_dict(component, refs)
        .and_then(|d| {
            d.get_item(refs.attrs.style_fold_root.bind(py))
                .ok()
                .flatten()
        })
        .is_some()
}

/// M2: per-class memo — does `App.style` have an entry for this class?
/// Mirrors the legacy gate's `style.get(type(self))` /
/// `style.get(self.create)` probes (`_get_component_style` uses the same
/// two keys). Per-call cache: `App.style` is fixed within one compile.
fn style_fold_entry_present(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<bool, PyReadError> {
    let py = component.py();
    let ty_key = component.get_type().as_ptr() as usize;
    if let Some(v) = refs.style_fold_entries.borrow().get(&ty_key) {
        return Ok(*v);
    }
    let style_obj = refs
        .style_fold_style
        .borrow()
        .as_ref()
        .map(|s| s.clone_ref(py));
    let Some(style_obj) = style_obj else {
        return Ok(false);
    };
    let style = style_obj.bind(py);
    // Legacy short-circuit: `not style` — an empty App.style has no entries.
    let present = if !style.is_truthy().unwrap_or(false) {
        false
    } else {
        let by_class = style
            .call_method1("get", (component.get_type(),))
            .map(|v| !v.is_none())
            .unwrap_or(false);
        by_class
            || component
                .getattr(refs.attrs.m_create.bind(py))
                .and_then(|create| style.call_method1("get", (create,)))
                .map(|v| !v.is_none())
                .unwrap_or(false)
    };
    refs.style_fold_entries.borrow_mut().insert(ty_key, present);
    Ok(present)
}

/// M2: replicate the legacy `_add_style_recursive` per-node gate and, for
/// folding nodes, call the Python `_apply_style_fold` — which mutates
/// `self.style` exactly as the legacy fold did. Must run BEFORE any
/// style/var-data read of the node. Gate (component.py fast path): skip
/// iff `isinstance(self.style, dict)` AND the class has no `add_style`
/// MRO chain AND `_add_style` is the base implementation AND `App.style`
/// has no entry for the class.
fn maybe_fold_style(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<(), PyReadError> {
    let py = component.py();
    let class_base = class_bool_flag(
        component,
        refs,
        |m| m.style_fold_base,
        |m, v| m.style_fold_base = Some(v),
        || {
            let ty = component.get_type();
            ty.getattr(refs.attrs.m_add_style.bind(py))
                .map(|f| f.is(&refs.component_add_style_base))
                .unwrap_or(false)
                && ty
                    .call_method1(
                        refs.attrs.m_iter_parent_classes_with_method.bind(py),
                        ("add_style",),
                    )
                    .and_then(|chain| chain.len())
                    .map(|len| len == 0)
                    .unwrap_or(false)
        },
    );
    let needs_fold = !class_base || style_fold_entry_present(component, refs)? || {
        // Per-node half: a non-dict style (raw Var assigned via
        // `_unsafe_create`) still takes the fold. `read_field` probes
        // the instance dict and falls back to the SHARED class default
        // — unlike getattr, it doesn't materialize a fresh `Style()`
        // per unset-style node through the descriptor factory.
        let inst_dict = crate::pyo3_reader::instance_dict(component, refs);
        match read_field(
            component,
            inst_dict.as_ref(),
            "style",
            &refs.attrs.style,
            refs,
        ) {
            Some(style) => style.downcast::<pyo3::types::PyDict>().is_err(),
            None => false,
        }
    };
    if needs_fold {
        let style_obj = refs
            .style_fold_style
            .borrow()
            .as_ref()
            .map(|s| s.clone_ref(py));
        if let Some(style_obj) = style_obj {
            refs.bump_crossings(1);
            component
                .call_method1(refs.attrs.m_apply_style_fold.bind(py), (style_obj,))
                .map_err(|source| PyReadError::Attr {
                    attr: "Component._apply_style_fold",
                    source,
                })?;
        }
    }
    Ok(())
}

/// Phase II (immutable components): the construction-staged var harvest —
/// the `_vars_cache` tuple primed by the arena fast path at create time.
/// `None` when the component wasn't staged, or a post-create write to a
/// harvest field invalidated it (`Component.__setattr__`).
fn staged_vars_items<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Option<Vec<Bound<'py, PyAny>>> {
    let py = component.py();
    let d = crate::pyo3_reader::instance_dict(component, refs)?;
    let cached = d.get_item(refs.attrs.vars_cache.bind(py)).ok().flatten()?;
    let tuple = cached.downcast_into::<pyo3::types::PyTuple>().ok()?;
    Some(tuple.iter().collect())
}

/// Phase II gate, imports half: the staged tuple may replace the Python
/// `_get_vars` walk in `build_imports_dict` only when the class keeps the
/// base `_get_vars` (forms.py overrides it to add extra vars).
fn vars_native_safe(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> bool {
    class_bool_flag(
        component,
        refs,
        |m| m.vars_native_safe,
        |m, v| m.vars_native_safe = Some(v),
        || {
            component
                .get_type()
                .getattr("_get_vars")
                .map(|f| {
                    f.is(&refs.component_get_vars_base)
                        || refs.bare_get_vars.as_ref().is_some_and(|b| f.is(b))
                })
                .unwrap_or(false)
        },
    )
}

/// Phase II gate, hooks half: the staged tuple may replace the whole
/// `_get_hooks_internal` chain only when every method in the chain is the
/// base implementation.
fn hooks_internal_native_safe(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> bool {
    class_bool_flag(
        component,
        refs,
        |m| m.hooks_internal_native_safe,
        |m, v| m.hooks_internal_native_safe = Some(v),
        || {
            let ty = component.get_type();
            [
                ("_get_vars", &refs.component_get_vars_base),
                ("_get_vars_hooks", &refs.component_get_vars_hooks_base),
                ("_get_events_hooks", &refs.component_get_events_hooks_base),
                (
                    "_get_hooks_internal",
                    &refs.component_get_hooks_internal_base,
                ),
                ("_get_ref_hook", &refs.component_get_ref_hook_base),
                (
                    "_get_mount_lifecycle_hook",
                    &refs.component_get_mount_lifecycle_hook_base,
                ),
            ]
            .iter()
            .all(|(name, base)| {
                ty.getattr(*name)
                    .map(|f| {
                        f.is(*base)
                            || (*name == "_get_vars"
                                && refs.bare_get_vars.as_ref().is_some_and(|b| f.is(b)))
                    })
                    .unwrap_or(false)
            })
        },
    )
}

/// B: a class-level boolean fact, cached on `ClassMetadata`. `get`/`set`
/// select the field; `compute` runs once per class.
fn class_bool_flag(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    get: impl Fn(&crate::pyo3_reader::ClassMetadata) -> Option<bool>,
    set: impl Fn(&mut crate::pyo3_reader::ClassMetadata, bool),
    compute: impl FnOnce() -> bool,
) -> bool {
    let key = component.get_type().as_ptr() as usize;
    if let Some(cache_rc) = &refs.class_cache {
        if let Some(meta) = cache_rc.borrow().get(&key) {
            if let Some(v) = get(meta) {
                return v;
            }
        }
    }
    let v = compute();
    if let Some(cache_rc) = &refs.class_cache {
        set(cache_rc.borrow_mut().entry(key).or_default(), v);
    }
    v
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

/// Harvest `_get_app_wrap_components` into the session-provided
/// accumulator (`PyRefs::app_wraps`), replacing the separate Python
/// `_get_all_app_wrap_components` page walk. Only classes that override
/// the base staticmethod pay any Python call, and the expanded per-class
/// dict (own wraps plus wraps-of-wraps — what the legacy walk contributes
/// for one node of the class) is computed once per session; per node the
/// cost is one cached flag lookup plus, for override classes, one HashSet
/// probe per freeze.
fn collect_app_wraps(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<(), PyReadError> {
    let py = component.py();
    let Some(acc) = refs.app_wraps.borrow().as_ref().map(|d| d.clone_ref(py)) else {
        return Ok(());
    };
    let is_base = class_bool_flag(
        component,
        refs,
        |m| m.app_wrap_is_base,
        |m, v| m.app_wrap_is_base = Some(v),
        || {
            component
                .get_type()
                .getattr("_get_app_wrap_components")
                .map(|d| d.is(&refs.component_app_wrap_base))
                .unwrap_or(true)
        },
    );
    if is_base {
        return Ok(());
    }
    let key = component.get_type().as_ptr() as usize;
    if !refs.app_wraps_seen.borrow_mut().insert(key) {
        return Ok(());
    }
    let cached: Option<Py<PyAny>> = refs.class_cache.as_ref().and_then(|cache_rc| {
        cache_rc
            .borrow()
            .get(&key)
            .and_then(|m| m.app_wraps_dict.as_ref().map(|d| d.clone_ref(py)))
    });
    let class_dict = match cached {
        Some(d) => d,
        None => {
            let d = component
                .call_method0("_get_app_wrap_components")
                .map_err(|source| PyReadError::Attr {
                    attr: "_get_app_wrap_components",
                    source,
                })?;
            let own: Vec<Bound<PyAny>> = d
                .downcast::<PyDict>()
                .map(|dict| dict.values().iter().collect())
                .unwrap_or_default();
            for wrap in own {
                let sub = wrap
                    .call_method0("_get_all_app_wrap_components")
                    .map_err(|source| PyReadError::Attr {
                        attr: "_get_all_app_wrap_components",
                        source,
                    })?;
                d.call_method1("update", (sub,))
                    .map_err(|source| PyReadError::Attr {
                        attr: "app_wraps dict.update",
                        source,
                    })?;
            }
            let owned = d.unbind();
            if let Some(cache_rc) = &refs.class_cache {
                cache_rc.borrow_mut().entry(key).or_default().app_wraps_dict =
                    Some(owned.clone_ref(py));
            }
            owned
        }
    };
    acc.bind(py)
        .call_method1("update", (class_dict.bind(py),))
        .map_err(|source| PyReadError::Attr {
            attr: "app_wraps accumulator update",
            source,
        })?;
    Ok(())
}

pub fn freeze_component<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Snapshot, PyReadError> {
    // Per-phase timing: reset counters so `last_phase_timings_ns()`
    // reflects this single freeze. The total span (cumulative, includes
    // children + the wrapper-drain loop) drops at function end.
    timing::reset();
    let _total = TSpan::new(TF::FreezeTotal);
    // PR7: each freeze starts with a fresh dedup table so a Var
    // observed in a previous freeze doesn't alias into a wholly
    // different snapshot's `var_data` index.
    refs.var_data_dedup.borrow_mut().clear();
    refs.imports_seen.borrow_mut().clear();
    refs.app_wraps_seen.borrow_mut().clear();
    let mut builder = SnapshotBuilder::new();
    let mut pending: Vec<(i32, String, Py<PyAny>)> = Vec::new();
    // M2: the style fold starts inactive — it activates at the node
    // carrying the `_style_fold_root` mark (the page subtree the legacy
    // fold would have walked). App-wrap drains below stay unfolded: the
    // legacy path folds wrappers separately in `_app_root` compilation.
    let root_idx = freeze_node(py, root, &mut builder, refs, &mut pending, false)?;
    builder.set_root(root_idx);
    // Drain the wrapper queue. Each wrapper's own `freeze_node` walk
    // may push more wrappers via its descendants — we keep draining
    // until the queue is empty.
    while let Some((sort_key, name, wrapper_py)) = pending.pop() {
        let wrapper = wrapper_py.bind(py).clone();
        let wrapper_root = freeze_node(py, &wrapper, &mut builder, refs, &mut pending, false)?;
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
    fold: bool,
) -> Result<NodeIdx, PyReadError> {
    let slot = builder.reserve();
    freeze_into_slot(py, component, slot, builder, refs, pending, fold)?;
    Ok(slot)
}

/// Fill a pre-reserved arena slot with `component`'s snapshot data,
/// pushing descendants past the slot. Sibling-aware: when called on a
/// parent, the parent first reserves a contiguous block of child
/// slots and only then recurses into each — this keeps every node's
/// `children` range a strict slice of *direct* children, never
/// straying into grandchildren further down the arena.
#[allow(clippy::too_many_arguments)]
fn freeze_into_slot<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
    fold: bool,
) -> Result<(), PyReadError> {
    // Capture id(component) so callers can map the snapshot back to
    // live Python Components without a second tree walk (used by the
    // precomputed memoize-decision path).
    builder.set_pyid(self_idx, component.as_ptr() as usize);
    // A/C: per-class visit tick (drives skip-list revalidation) +
    // boundary-crossing counter (exposed via
    // CompilerSession.freeze_pyo3_call_count for the A perf test).
    class_visit_tick(component, refs);

    // M2 deferred style fold: activate at the marked fold root, then
    // fold this node (if the legacy gate says so) BEFORE any read of
    // its style or var-data below.
    let fold = fold || style_fold_mark_present(component, refs);
    if fold {
        maybe_fold_style(component, refs)?;
    }

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
    let (cls, kind, tag, style_key) = {
        let _s = TSpan::new(TF::FreezeStructural);
        let cls = class_name(component)?;
        let (kind, tag) = classify(component, &cls, refs)?;
        let style_key = read_qualname(component, refs)?;
        (cls, kind, tag, style_key)
    };

    // Pre-reserve a contiguous block of slots for the direct children
    // BEFORE recursing into any of them. Each child's descendants land
    // past `children_end`, so the range stays a tight bound on direct
    // children only. For non-structural kinds (e.g. Match: arm bodies
    // live in `control_flow.match_arms`, not in `children`), the
    // range stays empty.
    let (children_start, children_end) = if kind.has_children() {
        freeze_children_for(py, component, kind, self_idx, builder, refs, pending, fold)?
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
    let imports = {
        let _s = TSpan::new(TF::FreezeImports);
        let imports = read_imports_summary(py, component, refs)?;
        // PR7 follow-through: prop-Components (Components embedded in Var
        // values for props) aren't visited by the snapshot tree walk, but
        // their imports still need to land in the bun-install dict.
        // Visit them once per `id(component)`.
        merge_prop_components_imports(py, component, refs)?;
        imports
    };
    let (custom_code, dynamic_imports, ref_name) = {
        let _s = TSpan::new(TF::FreezeOptional);
        collect_app_wraps(component, refs)?;
        let added = read_added_custom_code(component, refs)?;
        if !added.is_empty() {
            builder
                .snapshot_mut()
                .control_flow
                .custom_code_extra
                .insert(self_idx, added);
        }
        (
            read_custom_code(component, refs)?,
            read_dynamic_imports(component, refs)?,
            read_ref_name(component)?,
        )
    };
    let (hooks_internal, hooks_user) = {
        let _s = TSpan::new(TF::FreezeHooks);
        (
            read_hooks_internal(component, refs)?,
            read_hooks_user(component, refs)?,
        )
    };

    // Stage 4 per-node render-time harvests. Element nodes capture
    // `Tag.props` (already camelCased + LiteralVar-wrapped) as
    // `(name, js_expr)` pairs, plus event-trigger handlers as
    // `(camelCasedTrigger, js_expr)` pairs. Other node kinds skip the
    // `_render()` call because their JSX shape doesn't carry props.
    let mut props_have_reactive_var = false;
    let mut vars_used: SmallVec<[VarDataRef; 4]> = SmallVec::new();
    let (rendered_props, event_callbacks, style, rename_props) =
        if matches!(kind, NodeKind::Element) {
            // Classes that override `_render` mutate the prop set
            // imperatively (Form swaps `on_submit` for its named
            // `handleSubmit_*` handler, etc.) — source props/events/spreads
            // from the rendered Tag for those, exactly like legacy. Base
            // `_render` classes keep the fast raw-field path, which applies
            // the same declarative steps (`_exclude_props`, identity props,
            // custom_attrs) itself.
            let render_is_base = class_bool_flag(
                component,
                refs,
                |m| m.render_is_base,
                |m, v| m.render_is_base = Some(v),
                || {
                    component
                        .get_type()
                        .getattr("_render")
                        .map(|f| f.is(&refs.component_render_base))
                        .unwrap_or(false)
                },
            );
            let (props, events) = if render_is_base {
                let excluded = read_excluded_props(component, refs)?;
                let props = {
                    let _s = TSpan::new(TF::FreezeProps);
                    read_rendered_props(
                        component,
                        refs,
                        builder,
                        &mut props_have_reactive_var,
                        &mut vars_used,
                        &excluded,
                    )?
                };
                read_raw_special_props(
                    component,
                    refs,
                    builder,
                    self_idx,
                    &mut props_have_reactive_var,
                    &mut vars_used,
                )?;
                let events = {
                    let _s = TSpan::new(TF::FreezeEvents);
                    read_event_callbacks(component, refs, &excluded)?
                };
                (props, events)
            } else {
                read_props_from_render_tag(
                    component,
                    refs,
                    builder,
                    self_idx,
                    &mut props_have_reactive_var,
                    &mut vars_used,
                )?
            };
            let style_sym = {
                let _s = TSpan::new(TF::FreezeStyle);
                read_style(component, refs)?
            };
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
        timing::incr(TC::ImportsFast);
        return Ok(imports);
    }
    timing::incr(TC::ImportsSlow);
    let _slow = TSpan::new(TF::FreezeImportsSlow);

    // Full Rust reimplementation of `Component._get_imports()`: build the same
    // `{lib: [ImportVar]}` dict by merging the sources in `_get_imports`' order,
    // then feed the existing summary + bun accumulator. Avoids `_get_imports`'
    // Python `merge_parsed_imports`/`dict(...)`/comprehension overhead. Only the
    // BASE formula is reproduced — classes that override `_get_imports`
    // (e.g. `NoSSRComponent` rewrites the library import + adds dynamic-import
    // handling) call their override. `_get_vars()` stays the canonical var
    // enumerator, so output is byte-identical.
    let is_base = class_bool_flag(
        component,
        refs,
        |m| m.imports_is_base,
        |m, v| m.imports_is_base = Some(v),
        || {
            component
                .get_type()
                .getattr(refs.attrs.m_get_imports.bind(py))
                .map(|f| f.is(&refs.component_get_imports_base))
                .unwrap_or(false)
        },
    );
    let imports_dict = if is_base {
        build_imports_dict(py, component, refs)?
    } else {
        let imports_obj =
            match refs.cached_method(component, refs.attrs.m_get_imports.bind(py), |c| {
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
        match imports_obj.downcast_into::<PyDict>() {
            Ok(d) => d,
            Err(_) => return Ok(SmallVec::new()),
        }
    };
    if refs
        .imports_seen
        .borrow_mut()
        .insert(component.as_ptr() as usize)
    {
        merge_imports_dict_into_bun(py, &imports_dict, refs);
    }
    imports_summary_from_dict(py, &imports_dict, refs)
}

/// Append `value` to `result[lib]`, creating the list on first use. The
/// returned/created `PyList` is the same object stored in `result`, so
/// in-place `append` mutates the dict entry.
fn imports_list_for<'py>(
    result: &Bound<'py, PyDict>,
    lib: &Bound<'py, PyAny>,
) -> Result<Bound<'py, PyList>, PyReadError> {
    let attr = |source| PyReadError::Attr {
        attr: "imports dict list",
        source,
    };
    match result.get_item(lib).map_err(attr)? {
        Some(existing) => {
            existing
                .downcast_into::<PyList>()
                .map_err(|e| PyReadError::TypeMismatch {
                    attr: "imports dict entry",
                    expected: "list",
                    got: e.to_string(),
                })
        }
        None => {
            let list = PyList::empty_bound(result.py());
            result.set_item(lib, &list).map_err(attr)?;
            Ok(list)
        }
    }
}

/// `result[lib].extend(fields)` for every `(lib, fields)` in `src`, mirroring
/// `merge_parsed_imports`' per-lib list concatenation (insertion order, no
/// dedup). `fields` is any iterable of `ImportVar`s.
/// Append a `VarData.imports`-shaped tuple of `(lib, ImportVars)` pairs into
/// `result`, preserving pair order (the `merge_imports(*pairs)` semantics —
/// no last-wins collapsing).
/// The Python half of `build_imports_dict` step 5: walk `_get_vars()` and
/// merge each var's `dict(var_data.imports)`. Used when the node has no
/// staged `_vars_cache` (or its class/vars fail the native gates).
fn build_imports_var_walk<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
    result: &Bound<'py, PyDict>,
) -> Result<(), PyReadError> {
    if let Ok(vars) = component.call_method0("_get_vars") {
        if let Ok(iter) = vars.iter() {
            for var in iter.flatten() {
                let var_data =
                    match refs.call_cached0(&var, refs.attrs.m_get_all_var_data.bind(py), |c| {
                        &mut c.get_all_var_data
                    }) {
                        Ok(vd) if !vd.is_none() => vd,
                        _ => continue,
                    };
                let Ok(imports_obj) = var_data.getattr("imports") else {
                    continue;
                };
                // `dict(var_data.imports)`: tuple-of-pairs -> last-wins dict.
                let Ok(vi) = refs.dict_builtin.call1((imports_obj,)) else {
                    continue;
                };
                if let Ok(d) = vi.downcast::<PyDict>() {
                    extend_imports_dict(result, d)?;
                }
            }
        }
    }
    Ok(())
}

fn extend_imports_pairs<'py>(
    result: &Bound<'py, PyDict>,
    pairs: &Bound<'py, PyAny>,
) -> Result<(), PyReadError> {
    let Ok(iter) = pairs.iter() else {
        return Ok(());
    };
    for pair in iter.flatten() {
        let Ok(lib) = pair.get_item(0) else { continue };
        let Ok(fields) = pair.get_item(1) else {
            continue;
        };
        let target = imports_list_for(result, &lib)?;
        let Ok(fiter) = fields.iter() else { continue };
        for field in fiter.flatten() {
            let _ = target.append(field);
        }
    }
    Ok(())
}

fn extend_imports_dict<'py>(
    result: &Bound<'py, PyDict>,
    src: &Bound<'py, PyDict>,
) -> Result<(), PyReadError> {
    for (lib, fields) in src.iter() {
        let target = imports_list_for(result, &lib)?;
        let Ok(iter) = fields.iter() else { continue };
        for field in iter.flatten() {
            let _ = target.append(field);
        }
    }
    Ok(())
}

/// Build the `{lib: [ImportVar]}` dict that `Component._get_imports()` returns,
/// merging in its exact order: dependency imports, hook imports, the component's
/// own library import, event imports, per-Var `var_data.imports`, then
/// `add_imports` overrides.
fn build_imports_dict<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<Bound<'py, PyDict>, PyReadError> {
    let result = PyDict::new_bound(py);
    let inst_dict = instance_dict(component, refs);

    // 1. _get_dependencies_imports() (lib_dependencies, render=False entries).
    //    `{dep: [ImportVar(render=False)] for dep in self.lib_dependencies}` —
    //    skip the Python call when `lib_dependencies` is empty (the cached
    //    class default for almost every component).
    let lib_deps_empty = match read_field(
        component,
        inst_dict.as_ref(),
        "lib_dependencies",
        &refs.attrs.lib_dependencies,
        refs,
    ) {
        Some(v) if !v.is_none() => !v.is_truthy().unwrap_or(true),
        _ => true,
    };
    if !lib_deps_empty {
        if let Ok(deps) = component.call_method0("_get_dependencies_imports") {
            if let Ok(d) = deps.downcast::<PyDict>() {
                extend_imports_dict(&result, d)?;
            }
        }
    }
    // 2. Hooks-implied imports — derived from already-frozen data instead
    //    of calling `_get_hooks_imports()`, which re-renders the ref hook,
    //    the mount-lifecycle event chains, and the user hooks just to read
    //    their imports. Mirrors that method exactly: ref ⇒ useRef/refs;
    //    on_mount/on_unmount ⇒ useEffect; then the `_get_hooks()` Var's
    //    var_data imports and each `_get_added_hooks()` VarData's imports.
    //    The user-hook calls share the per-node method cache with
    //    `read_hooks_user`, so each still runs once per node.
    if ref_is_present(component) {
        if let Ok(d) = refs.ref_hook_imports.downcast::<PyDict>() {
            extend_imports_dict(&result, d)?;
        }
    }
    let event_triggers_field = read_field(
        component,
        inst_dict.as_ref(),
        "event_triggers",
        &refs.attrs.event_triggers,
        refs,
    );
    if let Some(triggers) = &event_triggers_field {
        if let Ok(d) = triggers.downcast::<PyDict>() {
            let has_lifecycle = ["on_mount", "on_unmount"].iter().any(|k| {
                d.get_item(k)
                    .ok()
                    .flatten()
                    .map(|v| !v.is_none())
                    .unwrap_or(false)
            });
            if has_lifecycle {
                if let Ok(li) = refs.lifecycle_hook_imports.downcast::<PyDict>() {
                    extend_imports_dict(&result, li)?;
                }
            }
        }
    }
    if !skip_method(component, refs, SkippableMethod::GetHooks) {
        if let Ok(v) = refs.call_cached0(component, refs.attrs.m_get_hooks.bind(py), |c| {
            &mut c.get_hooks
        }) {
            if !v.is_none() && !v.is_instance_of::<pyo3::types::PyString>() {
                if let Ok(vd) = refs.call_cached0(&v, refs.attrs.m_get_all_var_data.bind(py), |c| {
                    &mut c.get_all_var_data
                }) {
                    if !vd.is_none() {
                        if let Ok(pairs) = vd.getattr("imports") {
                            extend_imports_pairs(&result, &pairs)?;
                        }
                    }
                }
            }
        }
    }
    if !skip_method(component, refs, SkippableMethod::GetAddedHooks) {
        if let Ok(v) = refs.call_cached0(component, refs.attrs.m_get_added_hooks.bind(py), |c| {
            &mut c.get_added_hooks
        }) {
            if let Ok(d) = v.downcast::<PyDict>() {
                for (_k, vd) in d.iter() {
                    if vd.is_none() {
                        continue;
                    }
                    if let Ok(pairs) = vd.getattr("imports") {
                        extend_imports_pairs(&result, &pairs)?;
                    }
                }
            }
        }
    }
    // 3. The component's own library import: {library: [import_var]} when both
    //    `library` and `tag` are set. B: `library`/`tag` are almost always
    //    class-level defaults — read via the per-class default cache.
    let library = read_field(
        component,
        inst_dict.as_ref(),
        "library",
        &refs.attrs.library,
        refs,
    );
    let tag = read_field(component, inst_dict.as_ref(), "tag", &refs.attrs.tag, refs);
    if let (Some(lib), Some(tg)) = (&library, &tag) {
        if !lib.is_none() && !tg.is_none() {
            // `import_var` is a pure function of (tag, alias, is_default) —
            // memoize the property's result per distinct key per page so the
            // Python call + dataclass construction run once per key instead
            // of once per node. An exotic `is_default` value bypasses the
            // memo and calls the property directly.
            let alias = read_field(
                component,
                inst_dict.as_ref(),
                "alias",
                &refs.attrs.alias,
                refs,
            );
            let is_default = read_field(
                component,
                inst_dict.as_ref(),
                "is_default",
                &refs.attrs.is_default,
                refs,
            );
            let default_code = match &is_default {
                None => Some(0u8),
                Some(v) if v.is_none() => Some(1),
                Some(v) => match v.extract::<bool>() {
                    Ok(false) => Some(2),
                    Ok(true) => Some(3),
                    Err(_) => None,
                },
            };
            let memo_key = default_code.map(|code| {
                let alias_key = match &alias {
                    Some(a) if !a.is_none() => {
                        py_str(a).map(|s| format!("s:{s}")).unwrap_or_default()
                    }
                    _ => "n".to_owned(),
                };
                (py_str(tg).unwrap_or_default(), alias_key, code)
            });
            let cached = memo_key.as_ref().and_then(|k| {
                refs.import_var_memo
                    .borrow()
                    .get(k)
                    .map(|o| o.bind(py).clone())
            });
            let import_var = match cached {
                Some(iv) => Some(iv),
                None => match component.getattr(refs.attrs.import_var.bind(py)) {
                    Ok(iv) => {
                        if let Some(k) = memo_key {
                            refs.import_var_memo
                                .borrow_mut()
                                .insert(k, iv.clone().unbind());
                        }
                        Some(iv)
                    }
                    Err(_) => None,
                },
            };
            if let Some(iv) = import_var {
                let _ = imports_list_for(&result, lib)?.append(iv);
            }
        }
    }
    // 4. Imports.EVENTS when the component has event triggers (the field
    //    was already read for the step-2 lifecycle check).
    if let Some(triggers) = &event_triggers_field {
        if triggers.is_truthy().unwrap_or(false) {
            if let Ok(d) = refs.events_imports.downcast::<PyDict>() {
                extend_imports_dict(&result, d)?;
            }
        }
    }
    // 5. var_imports: `dict(var_data.imports)` for each Var the component uses.
    //    Phase II fast path: the construction-staged `_vars_cache` tuple is
    //    read natively when every entry is a native var — no `_get_vars`
    //    generator and no per-var `_get_all_var_data` Python calls. The
    //    `native_var` gate guarantees `_get_all_var_data` is the base
    //    descriptor, so `var_data_ref()` is the same data the Python path
    //    reads through `PyVarData`.
    let mut staged_done = false;
    if vars_native_safe(component, refs) {
        if let Some(items) = staged_vars_items(component, refs) {
            {
                for v in &items {
                    let Some(rv) = native_var(v, refs) else {
                        // Per-var Python fallback (e.g. ArgsFunctionOperation
                        // in event chains): the exact per-var body of
                        // `build_imports_var_walk`.
                        if let Ok(vd) =
                            refs.call_cached0(v, refs.attrs.m_get_all_var_data.bind(py), |c| {
                                &mut c.get_all_var_data
                            })
                        {
                            if !vd.is_none() {
                                if let Ok(imports_obj) = vd.getattr("imports") {
                                    if let Ok(vi) = refs.dict_builtin.call1((imports_obj,)) {
                                        if let Ok(d) = vi.downcast::<PyDict>() {
                                            extend_imports_dict(&result, d)?;
                                        }
                                    }
                                }
                            }
                        }
                        continue;
                    };
                    let Some(vd) = rv.var_data_ref() else {
                        continue;
                    };
                    if vd.imports.is_empty() {
                        continue;
                    }
                    // `dict(var_data.imports)`: tuple-of-pairs → last-wins
                    // value, first-seen key order — replicated before the
                    // extend, exactly like the Python path below.
                    let mut ordered: Vec<(&String, &Vec<reflex_vars::ImportVar>)> =
                        Vec::with_capacity(vd.imports.len());
                    for (lib, ivs) in &vd.imports {
                        if let Some(slot) = ordered.iter_mut().find(|(l, _)| *l == lib) {
                            slot.1 = ivs;
                        } else {
                            ordered.push((lib, ivs));
                        }
                    }
                    for (lib, ivs) in ordered {
                        let lib_obj = PyString::new_bound(py, lib).into_any();
                        let target = imports_list_for(&result, &lib_obj)?;
                        for iv in ivs {
                            let obj =
                                Bound::new(py, reflex_vars::PyImportVar::from_struct(iv.clone()))
                                    .map_err(|source| PyReadError::Attr {
                                    attr: "PyImportVar::from_struct",
                                    source,
                                })?;
                            let _ = target.append(obj);
                        }
                    }
                }
                staged_done = true;
            }
        }
    }
    if !staged_done {
        build_imports_var_walk(py, component, refs, &result)?;
    }
    // 6. add_imports overrides: parse_imports(clz.add_imports(self)) per class.
    if let Ok(classes) = component.call_method1(
        refs.attrs.m_iter_parent_classes_with_method.bind(py),
        ("add_imports",),
    ) {
        if let Ok(iter) = classes.iter() {
            for clz in iter.flatten() {
                let Ok(added) = clz.call_method1("add_imports", (component,)) else {
                    continue;
                };
                if let Ok(list) = added.downcast::<PyList>() {
                    for item in list.iter() {
                        if let Ok(parsed) = refs.parse_imports.call1((item,)) {
                            if let Ok(d) = parsed.downcast::<PyDict>() {
                                extend_imports_dict(&result, d)?;
                            }
                        }
                    }
                } else if let Ok(parsed) = refs.parse_imports.call1((&added,)) {
                    if let Ok(d) = parsed.downcast::<PyDict>() {
                        extend_imports_dict(&result, d)?;
                    }
                }
            }
        }
    }
    Ok(result)
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
    let inst_dict = instance_dict(component, refs);
    let has_rendered_import = match (
        read_field(
            component,
            inst_dict.as_ref(),
            "library",
            &refs.attrs.library,
            refs,
        ),
        read_field(component, inst_dict.as_ref(), "tag", &refs.attrs.tag, refs),
    ) {
        (Some(library), Some(tag)) if !library.is_none() && !tag.is_none() => {
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
    // B: probe the instance `__dict__` + per-class defaults instead of
    // descriptor-protocol getattrs for every field below.
    let inst_dict = instance_dict(component, refs);
    // Sources of *non-library* imports the fast path doesn't reproduce. If any
    // is present, defer to `_get_imports()`:
    //  - event_triggers   -> `Imports.EVENTS` + event-callback hook imports
    //  - lib_dependencies  -> `_get_dependencies_imports`
    //  - special_props     -> their own Vars' imports
    //  - custom_attrs      -> values may be import-bearing Vars
    for (raw, interned) in [
        ("event_triggers", &refs.attrs.event_triggers),
        ("lib_dependencies", &refs.attrs.lib_dependencies),
        ("custom_attrs", &refs.attrs.custom_attrs),
        ("special_props", &refs.attrs.special_props),
    ] {
        let empty = match read_field(component, inst_dict.as_ref(), raw, interned, refs) {
            Some(v) if !v.is_none() => !v.is_truthy().unwrap_or(true),
            _ => true,
        };
        if !empty {
            return Ok(false);
        }
    }
    // `key`/`id`/`class_name` stay strict: their str values can encode
    // f-string `VarData`, and a set `id` typically induces a `useRef` hook
    // import — both add imports the fast path doesn't reproduce.
    for (raw, interned) in [
        ("key", &refs.attrs.key),
        ("id", &refs.attrs.id),
        ("class_name", &refs.attrs.class_name),
    ] {
        let present = matches!(
            read_field(component, inst_dict.as_ref(), raw, interned, refs),
            Some(v) if !v.is_none()
        );
        if present {
            return Ok(false);
        }
    }
    // A ref emits a `useRef` hook -> `react` import via `_get_hooks_imports`.
    if ref_is_present(component) {
        return Ok(false);
    }
    // Unlike the old gate (which bailed on *any* prop or style), styled /
    // propped nodes are fine as long as their Vars carry no imports — only
    // import-bearing Vars are merged by `_get_imports`' `var_imports`. `style`
    // and prop Vars are the only remaining var sources (events / special_props
    // / custom_attrs already excluded above), mirroring `_get_vars`.
    if style_var_has_imports(component, refs)? {
        return Ok(false);
    }
    for (raw, interned_name) in class_get_prop_names(component, refs)? {
        let Some(value) = read_field(component, inst_dict.as_ref(), &raw, &interned_name, refs)
        else {
            continue;
        };
        if value.is_none() {
            continue;
        }
        if var_has_imports(&value, refs)? {
            return Ok(false);
        }
    }
    Ok(true)
}

/// `True` when `component.get_ref()` returns a truthy ref name (the node will
/// emit a `useRef` hook, pulling a `react` import that the library-only fast
/// path doesn't account for).
fn ref_is_present(component: &Bound<'_, PyAny>) -> bool {
    match component.call_method0("get_ref") {
        Ok(v) => v.is_truthy().unwrap_or(false),
        Err(_) => false,
    }
}

/// `True` when a Var value carries a non-empty `VarData.imports` (so
/// `_get_imports` would merge those imports for this component).
fn var_has_imports<'py>(
    value: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<bool, PyReadError> {
    if let Some(rv) = native_var(value, refs) {
        return Ok(rv
            .var_data_ref()
            .map(|vd| !vd.imports.is_empty())
            .unwrap_or(false));
    }
    let py = value.py();
    if !crate::pyo3_reader::is_var_value(value, &refs.var_cls).unwrap_or(false) {
        return Ok(false);
    }
    let var_data = match refs.call_cached0(value, refs.attrs.m_get_all_var_data.bind(py), |c| {
        &mut c.get_all_var_data
    }) {
        Ok(vd) if !vd.is_none() => vd,
        _ => return Ok(false),
    };
    Ok(var_data_has_imports(&var_data))
}

/// `True` when the component's `style` carries a non-empty `VarData.imports`.
/// `_get_vars` yields a synthetic `style` Var whose data is `self.style`'s
/// `_var_data`, so a reactive style with imports must defer to `_get_imports`.
fn style_var_has_imports<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<bool, PyReadError> {
    let py = component.py();
    let style = match component.getattr(refs.attrs.style.bind(py)) {
        Ok(s) if !s.is_none() => s,
        _ => return Ok(false),
    };
    let Ok(var_data) = style.getattr("_var_data") else {
        return Ok(false);
    };
    if var_data.is_none() {
        return Ok(false);
    }
    Ok(var_data_has_imports(&var_data))
}

/// `True` when a `VarData`'s `imports` is non-empty.
fn var_data_has_imports(var_data: &Bound<'_, PyAny>) -> bool {
    match var_data.getattr("imports") {
        Ok(imp) => imp.is_truthy().unwrap_or(false),
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

/// Read the ``add_custom_code`` MRO chain (the chain half of legacy
/// ``_get_all_custom_code``): each parent class with an override is
/// called with the instance and contributes its blocks in MRO order.
/// Gated per class — chain-less classes (the overwhelming majority) pay
/// one cached probe and never walk.
fn read_added_custom_code<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[Symbol; 2]>, PyReadError> {
    let py = component.py();
    let mut out: SmallVec<[Symbol; 2]> = SmallVec::new();
    let chain_empty = class_bool_flag(
        component,
        refs,
        |m| m.add_custom_code_chain_empty,
        |m, v| m.add_custom_code_chain_empty = Some(v),
        || parent_method_chain_is_empty(py, component, refs, "add_custom_code"),
    );
    if chain_empty {
        return Ok(out);
    }
    let chain = component
        .call_method1(
            refs.attrs.m_iter_parent_classes_with_method.bind(py),
            ("add_custom_code",),
        )
        .map_err(|source| PyReadError::Attr {
            attr: "_iter_parent_classes_with_method(add_custom_code)",
            source,
        })?;
    let iter = chain.iter().map_err(|source| PyReadError::Attr {
        attr: "iter(add_custom_code chain)",
        source,
    })?;
    for clz in iter {
        let clz = clz.map_err(|source| PyReadError::Attr {
            attr: "add_custom_code chain entry",
            source,
        })?;
        let Ok(items) = clz.call_method1("add_custom_code", (component,)) else {
            continue;
        };
        let Ok(items_iter) = items.iter() else {
            continue;
        };
        for item in items_iter.flatten() {
            let s = py_str(&item)?;
            if !s.is_empty() {
                out.push(intern(&s));
            }
        }
    }
    Ok(out)
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
    // Phase II (immutable components): the construction-staged var harvest
    // replaces the `_get_hooks_internal` chain when the class keeps the
    // chain's base methods. Composition mirrors the Python dict merge —
    // events hooks (a CONSTANT, `Hooks.EVENTS`, whenever the node has
    // triggers), then the ref hook and mount-lifecycle hook (small Python
    // calls made only when id / on_mount/on_unmount are present — chain
    // rendering stays in Python), then the staged vars hooks read natively.
    // Hook positions are INTERNAL throughout: native `VarData` stores flat
    // hook lines and the `PyVarData.position` getter is always None, so
    // the Python path resolves every entry to position 0 as well.
    if hooks_internal_native_safe(component, refs) {
        if let Some(items) = staged_vars_items(component, refs) {
            {
                let inst_dict = crate::pyo3_reader::instance_dict(component, refs);
                let triggers = read_field(
                    component,
                    inst_dict.as_ref(),
                    "event_triggers",
                    &refs.attrs.event_triggers,
                    refs,
                );
                let mut seen: SmallVec<[Symbol; 8]> = SmallVec::new();
                let push_entry = |out: &mut SmallVec<[HookEntry; N]>,
                                  seen: &mut SmallVec<[Symbol; 8]>,
                                  sym: Symbol| {
                    // dict-update semantics: first-seen order; later
                    // values all carry the same INTERNAL position, so
                    // dedup alone reproduces the merge.
                    if !seen.contains(&sym) {
                        seen.push(sym);
                        out.push(HookEntry::new(sym, 0));
                    }
                };
                let mut has_lifecycle = false;
                if let Some(t) = &triggers {
                    if t.is_truthy().unwrap_or(false) {
                        push_entry(&mut out, &mut seen, intern(&refs.hooks_events_code));
                        if let Ok(d) = t.downcast::<PyDict>() {
                            has_lifecycle = ["on_mount", "on_unmount"].iter().any(|k| {
                                d.get_item(k)
                                    .ok()
                                    .flatten()
                                    .map(|v| !v.is_none())
                                    .unwrap_or(false)
                            });
                        }
                    }
                }
                let id_set =
                    match read_field(component, inst_dict.as_ref(), "id", &refs.attrs.id, refs) {
                        Some(v) => !v.is_none(),
                        None => false,
                    };
                if id_set {
                    if let Ok(hook) = component.call_method0("_get_ref_hook") {
                        if !hook.is_none() {
                            if let Ok(code) = py_str(&hook) {
                                if !code.is_empty() {
                                    push_entry(&mut out, &mut seen, intern(&code));
                                }
                            }
                        }
                    }
                }
                if has_lifecycle {
                    if let Ok(hook) = component.call_method0("_get_mount_lifecycle_hook") {
                        if !hook.is_none() {
                            if let Ok(code) = py_str(&hook) {
                                if !code.is_empty() {
                                    push_entry(&mut out, &mut seen, intern(&code));
                                }
                            }
                        }
                    }
                }
                for v in &items {
                    if let Some(rv) = native_var(v, refs) {
                        let Some(vd) = rv.var_data_ref() else {
                            continue;
                        };
                        for code in &vd.hooks {
                            if code.is_empty() {
                                continue;
                            }
                            push_entry(&mut out, &mut seen, intern(code));
                        }
                        continue;
                    }
                    // Per-var Python fallback (e.g. ArgsFunctionOperation in
                    // event chains): same reads `_get_vars_hooks` performs —
                    // `.hooks` is a dict of code → VarData|None (positions
                    // honored) or an iterable of code strings (INTERNAL).
                    let Ok(vd) =
                        refs.call_cached0(v, refs.attrs.m_get_all_var_data.bind(py), |c| {
                            &mut c.get_all_var_data
                        })
                    else {
                        continue;
                    };
                    if vd.is_none() {
                        continue;
                    }
                    let Ok(hooks) = vd.getattr("hooks") else {
                        continue;
                    };
                    if let Ok(d) = hooks.downcast::<PyDict>() {
                        for (k, val) in d.iter() {
                            let code = py_str(&k)?;
                            if code.is_empty() {
                                continue;
                            }
                            // dict-update semantics: first-seen ORDER but
                            // last-wins POSITION on duplicate keys.
                            let sym = intern(&code);
                            let pos = read_hook_position(&val).unwrap_or(0);
                            if seen.contains(&sym) {
                                if let Some(entry) = out.iter_mut().find(|e| e.code == sym) {
                                    entry.position = pos;
                                }
                            } else {
                                seen.push(sym);
                                out.push(HookEntry::new(sym, pos));
                            }
                        }
                    } else if let Ok(iter) = hooks.iter() {
                        for k in iter.flatten() {
                            let code = py_str(&k)?;
                            if code.is_empty() {
                                continue;
                            }
                            push_entry(&mut out, &mut seen, intern(&code));
                        }
                    }
                }
                return Ok(out);
            }
        }
    }
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
/// Read the component's `_exclude_props()` list (legacy `_render` pops
/// these snake-named entries from the prop dict before rendering —
/// declared props, identity props, custom_attrs keys, AND event
/// triggers). Base classes (the overwhelming majority) pay one cached
/// identity probe and never call.
fn read_excluded_props<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Result<SmallVec<[String; 2]>, PyReadError> {
    let mut out: SmallVec<[String; 2]> = SmallVec::new();
    let is_base = class_bool_flag(
        component,
        refs,
        |m| m.exclude_props_is_base,
        |m, v| m.exclude_props_is_base = Some(v),
        || {
            component
                .get_type()
                .getattr("_exclude_props")
                .map(|f| f.is(&refs.component_exclude_props_base))
                .unwrap_or(false)
        },
    );
    if is_base {
        return Ok(out);
    }
    let Ok(names) = component.call_method0("_exclude_props") else {
        return Ok(out);
    };
    let Ok(iter) = names.iter() else {
        return Ok(out);
    };
    for name in iter.flatten() {
        let s = py_str(&name)?;
        if !s.is_empty() {
            out.push(s);
        }
    }
    Ok(out)
}

/// Render `component.special_props` (spread Vars) into the snapshot's
/// per-node spread table. Fast-path twin of the Tag's `special_props`.
fn read_raw_special_props(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    builder: &mut SnapshotBuilder,
    self_idx: NodeIdx,
    reactive_out: &mut bool,
    vars_used_out: &mut SmallVec<[VarDataRef; 4]>,
) -> Result<(), PyReadError> {
    let inst_dict = instance_dict(component, refs);
    let Some(special) = read_field(
        component,
        inst_dict.as_ref(),
        "special_props",
        &refs.attrs.special_props,
        refs,
    ) else {
        return Ok(());
    };
    collect_special_props(
        &special,
        refs,
        builder,
        self_idx,
        reactive_out,
        vars_used_out,
    )
}

/// Render an iterable of spread Vars (`...{expr}` props) into the
/// snapshot's per-node spread table, registering var data and the
/// reactivity flag like any other prop value.
fn collect_special_props(
    special: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    builder: &mut SnapshotBuilder,
    self_idx: NodeIdx,
    reactive_out: &mut bool,
    vars_used_out: &mut SmallVec<[VarDataRef; 4]>,
) -> Result<(), PyReadError> {
    if special.is_none() {
        return Ok(());
    }
    let Ok(iter) = special.iter() else {
        return Ok(());
    };
    let mut spreads: SmallVec<[Symbol; 1]> = SmallVec::new();
    for item in iter.flatten() {
        if !*reactive_out && var_has_reactive_data(&item, refs)? {
            *reactive_out = true;
        }
        if let Some(r) = register_var_data(&item, builder, refs)? {
            if !vars_used_out.contains(&r) {
                vars_used_out.push(r);
            }
        }
        let expr = render_value_as_js(&item, refs)?;
        if !expr.is_empty() {
            spreads.push(intern(&expr));
        }
    }
    if !spreads.is_empty() {
        builder
            .snapshot_mut()
            .control_flow
            .special_props
            .insert(self_idx, spreads);
    }
    Ok(())
}

/// Source props / event callbacks / spreads from `component._render()` —
/// the path for classes overriding `_render`, whose Tag carries
/// imperative prop edits (Form's `handleSubmit_*` swap, prop pops, etc.)
/// that raw field reads can't see. Mirrors legacy exactly: the Tag's
/// `props` dict is the final prop set (excludes already applied; keys
/// already camelized; `css` included — the emit dedups it against
/// `node.style`) and `EventChain` values route to `event_callbacks`.
fn read_props_from_render_tag(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    builder: &mut SnapshotBuilder,
    self_idx: NodeIdx,
    reactive_out: &mut bool,
    vars_used_out: &mut SmallVec<[VarDataRef; 4]>,
) -> Result<
    (
        SmallVec<[(Symbol, Symbol); 4]>,
        SmallVec<[(Symbol, Symbol); 2]>,
    ),
    PyReadError,
> {
    let py = component.py();
    let mut props: SmallVec<[(Symbol, Symbol); 4]> = SmallVec::new();
    let mut events: SmallVec<[(Symbol, Symbol); 2]> = SmallVec::new();
    let tag = component
        .call_method0("_render")
        .map_err(|source| PyReadError::Attr {
            attr: "Component._render()",
            source,
        })?;
    let event_chain_cls = py
        .import_bound("reflex_base.event")
        .and_then(|m| m.getattr("EventChain"))
        .map_err(|source| PyReadError::Attr {
            attr: "reflex_base.event.EventChain",
            source,
        })?;
    if let Ok(tag_props) = tag.getattr("props") {
        if let Ok(dict) = tag_props.downcast::<PyDict>() {
            for (key, value) in dict.iter() {
                let name = py_str(&key)?;
                if !*reactive_out && var_has_reactive_data(&value, refs)? {
                    *reactive_out = true;
                }
                if let Some(r) = register_var_data(&value, builder, refs)? {
                    if !vars_used_out.contains(&r) {
                        vars_used_out.push(r);
                    }
                }
                let expr = render_value_as_js(&value, refs)?;
                if expr.is_empty() {
                    continue;
                }
                if value.is_instance(&event_chain_cls).unwrap_or(false) {
                    events.push((intern(&name), intern(&expr)));
                } else {
                    props.push((intern(&name), intern(&expr)));
                }
            }
        }
    }
    if let Ok(special) = tag.getattr("special_props") {
        collect_special_props(
            &special,
            refs,
            builder,
            self_idx,
            reactive_out,
            vars_used_out,
        )?;
    }
    Ok((props, events))
}

fn read_rendered_props(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    builder: &mut SnapshotBuilder,
    reactive_out: &mut bool,
    vars_used_out: &mut SmallVec<[VarDataRef; 4]>,
    excluded: &SmallVec<[String; 2]>,
) -> Result<SmallVec<[(Symbol, Symbol); 4]>, PyReadError> {
    let mut raw_pairs: SmallVec<[(String, Symbol); 4]> = SmallVec::new();

    // B: one `__dict__` fetch per node; every field read below probes it
    // first and falls back to the per-class cached default, skipping the
    // `ComponentField.__get__` descriptor call for unset fields.
    let inst_dict = instance_dict(component, refs);

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
        if excluded.iter().any(|e| e == &attr_name) {
            continue;
        }
        let value_obj = match read_field(component, inst_dict.as_ref(), raw, interned_name, refs) {
            Some(v) => v,
            None => continue,
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
    for (name, interned) in [
        ("key", &refs.attrs.key),
        ("id", &refs.attrs.id),
        ("class_name", &refs.attrs.class_name),
    ] {
        if excluded.iter().any(|e| e == name) {
            continue;
        }
        let v = match read_field(component, inst_dict.as_ref(), name, interned, refs) {
            Some(v) if !v.is_none() => v,
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
    if let Some(custom) = read_field(
        component,
        inst_dict.as_ref(),
        "custom_attrs",
        &refs.attrs.custom_attrs,
        refs,
    ) {
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
                            if excluded.iter().any(|e| e == &name) {
                                continue;
                            }
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
    excluded: &SmallVec<[String; 2]>,
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
        if excluded.iter().any(|e| e == &trigger) {
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
///
/// Fast path for the base `Component._get_style` (the overwhelming common
/// case): read `self.style` directly and render the emotion object literal
/// in Rust, instead of calling `_get_style()` — which rebuilds the CSS
/// `Var` via `LiteralVar.create`, one `LiteralVar` per CSS property, on
/// every node. Classes that override `_get_style` (e.g. recharts'
/// `{"wrapperStyle": ...}`) keep the generic `_get_style` path so their
/// custom shape is preserved exactly.
fn read_style(component: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<Symbol, PyReadError> {
    let py = component.py();
    // Is `_get_style` the base implementation? If a subclass overrides it,
    // its result shape may differ (recharts returns no "css" key), so defer
    // to the generic path. Identity-compare the unbound function on the type
    // — once per class via the session cache.
    let is_base = class_bool_flag(
        component,
        refs,
        |m| m.style_is_base,
        |m, v| m.style_is_base = Some(v),
        || {
            component
                .get_type()
                .getattr(refs.attrs.m_get_style.bind(py))
                .map(|f| f.is(&refs.component_get_style_base))
                .unwrap_or(false)
        },
    );
    if !is_base {
        return read_style_via_get_style(component, refs);
    }
    // `read_field` over getattr: the instance-dict probe falls back to the
    // SHARED class default for unset styles instead of materializing a
    // fresh `Style()` per node through the descriptor factory (read-only
    // here — the empty-style short-circuit below renders nothing).
    let inst_dict = crate::pyo3_reader::instance_dict(component, refs);
    let style = match read_field(
        component,
        inst_dict.as_ref(),
        "style",
        &refs.attrs.style,
        refs,
    ) {
        Some(s) if !s.is_none() => s,
        _ => return Ok(Symbol::EMPTY),
    };
    // A whole-style reactive `Var` (`isinstance(self.style, Var)` branch of
    // `_get_style`) is its own `css` expression.
    if crate::pyo3_reader::is_var_value(&style, &refs.var_cls).unwrap_or(false) {
        let expr = render_value_as_js(&style, refs)?;
        return Ok(if expr.is_empty() {
            Symbol::EMPTY
        } else {
            intern(&expr)
        });
    }
    // Empty style → no `css` prop. On the base `_get_style` path the rendered
    // style is exactly `format_as_emotion(self.style)`, and that maps an empty
    // dict to an empty dict (the loop body never runs), so skip the Python
    // `format_as_emotion` call + its boundary crossing for unstyled nodes
    // (the majority — theme styling leaves most nodes with an empty `style`).
    // Safe only here, after the override check: a subclass `_get_style` may
    // synthesize style from other fields even when `self.style` is empty.
    if matches!(style.len(), Ok(0)) {
        return Ok(Symbol::EMPTY);
    }
    // A: emotion transform in Rust (pseudo-selectors, breakpoints, nesting)
    // — zero Python execution for the base path. Structures outside the
    // ported surface fall back to the Python `format_as_emotion` callback.
    if let Ok(style_dict) = style.downcast::<PyDict>() {
        match emotion_from_style(style_dict, refs)? {
            EmotionOutcome::Done(None) => return Ok(Symbol::EMPTY),
            EmotionOutcome::Done(Some(m)) => {
                return Ok(intern(&render_emotion_map(&m, refs)?));
            }
            EmotionOutcome::Fallback => {}
        }
    }
    let emotion = match refs.format_as_emotion.call1((&style,)) {
        Ok(e) if !e.is_none() => e,
        _ => return Ok(Symbol::EMPTY),
    };
    let Ok(d) = emotion.downcast::<PyDict>() else {
        return Ok(Symbol::EMPTY);
    };
    if d.is_empty() {
        return Ok(Symbol::EMPTY);
    }
    Ok(intern(&render_style_object(d, refs)?))
}

/// Generic `read_style` for components that override `_get_style`: call the
/// method and extract its `{"css": <expr>}` entry (the legacy contract).
fn read_style_via_get_style(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<Symbol, PyReadError> {
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

// ---- A: `format_as_emotion` in Rust ---------------------------------------
//
// Port of `reflex_base.style.format_as_emotion` for the base `_get_style`
// path. Inputs are `self.style` dicts whose values were already normalized
// by `Style.__init__`/`convert()` (scalars → LiteralVars, nested dicts /
// responsive lists converted recursively), so the transform here is purely
// structural: pseudo-selector key rewriting, breakpoint lists / `Breakpoints`
// → `@media` maps, nested-dict recursion, insertion-order preservation.
// VarData propagation is NOT reproduced because the rendered output never
// consumed it on this path: `render_style_object` reads only keys/values,
// and style VarData reaches hooks/imports via `_get_vars`' synthetic style
// Var (`self.style._var_data`), independent of this transform.
//
// Anything structurally unexpected returns `Fallback` and the caller uses
// the Python `format_as_emotion` exactly as before.

/// One emotion-map value: either a raw Python object (Var / scalar / raw
/// nested dict — rendered by `render_style_value`) or a sub-map built by
/// this pass.
enum EmotionVal<'py> {
    Raw(Bound<'py, PyAny>),
    Map(EmotionMap<'py>),
}

/// Insertion-ordered string-keyed map with Python-dict update semantics
/// (existing keys keep their position, value replaced).
struct EmotionMap<'py> {
    entries: Vec<(String, EmotionVal<'py>)>,
}

impl<'py> EmotionMap<'py> {
    fn new() -> Self {
        Self {
            entries: Vec::new(),
        }
    }

    fn insert(&mut self, key: String, val: EmotionVal<'py>) {
        if let Some(entry) = self.entries.iter_mut().find(|(k, _)| *k == key) {
            entry.1 = val;
        } else {
            self.entries.push((key, val));
        }
    }

    /// `dict.setdefault(key, {})` where the existing value must be a map
    /// (Python would crash calling `.update` on a non-dict — that can't
    /// happen in working styles, so a `Raw` collision falls back).
    fn setdefault_map(&mut self, key: &str) -> Option<&mut EmotionMap<'py>> {
        let idx = match self.entries.iter().position(|(k, _)| k == key) {
            Some(i) => i,
            None => {
                self.entries
                    .push((key.to_owned(), EmotionVal::Map(EmotionMap::new())));
                self.entries.len() - 1
            }
        };
        match &mut self.entries[idx].1 {
            EmotionVal::Map(m) => Some(m),
            EmotionVal::Raw(_) => None,
        }
    }
}

enum EmotionOutcome<'py> {
    /// Transform succeeded; `None` mirrors Python's `format_as_emotion`
    /// returning `None` for an empty result (→ no `css` prop).
    Done(Option<EmotionMap<'py>>),
    /// Structure outside the ported surface — use the Python callback.
    Fallback,
}

/// Exact port of `format.to_kebab_case`: the two `re.sub` passes of
/// `to_snake_case` (`(.)([A-Z][a-z]+)` then `([a-z0-9])([A-Z])`, both
/// → `\1_\2`), lowercase, `-`→`_`, then `_`→`-` for kebab.
fn to_kebab_case(text: &str) -> String {
    let cs: Vec<char> = text.chars().collect();
    // Pass 1: (.)([A-Z][a-z]+) -> \1_\2, leftmost non-overlapping.
    let mut pass1: Vec<char> = Vec::with_capacity(cs.len() + 4);
    let mut i = 0;
    while i < cs.len() {
        if i + 2 < cs.len() && cs[i + 1].is_ascii_uppercase() && cs[i + 2].is_ascii_lowercase() {
            pass1.push(cs[i]);
            pass1.push('_');
            pass1.push(cs[i + 1]);
            let mut j = i + 2;
            while j < cs.len() && cs[j].is_ascii_lowercase() {
                pass1.push(cs[j]);
                j += 1;
            }
            i = j;
        } else {
            pass1.push(cs[i]);
            i += 1;
        }
    }
    // Pass 2: ([a-z0-9])([A-Z]) -> \1_\2, leftmost non-overlapping.
    let mut out = String::with_capacity(pass1.len() + 4);
    let mut i = 0;
    while i < pass1.len() {
        out.push(pass1[i]);
        if (pass1[i].is_ascii_lowercase() || pass1[i].is_ascii_digit())
            && i + 1 < pass1.len()
            && pass1[i + 1].is_ascii_uppercase()
        {
            out.push('_');
            out.push(pass1[i + 1]);
            i += 2;
        } else {
            i += 1;
        }
    }
    out.to_lowercase().replace('-', "_").replace('_', "-")
}

/// Port of `_format_emotion_style_pseudo_selector`: `_x` → `&:` +
/// kebab(x), `:x` → `&` + kebab(:x); anything else passes through
/// unchanged (regular props were already camelCased by `convert`).
fn format_emotion_pseudo_selector(key: &str) -> String {
    let mut prefix: Option<&str> = None;
    let mut k = key;
    if let Some(stripped) = k.strip_prefix('_') {
        prefix = Some("&:");
        k = stripped;
    }
    if k.starts_with(':') {
        prefix = Some("&");
    }
    match prefix {
        Some(p) => format!("{p}{}", to_kebab_case(k)),
        None => key.to_owned(),
    }
}

fn media_query(breakpoint_expr: &str) -> String {
    format!("@media screen and (min-width: {breakpoint_expr})")
}

/// One `mbps` entry value: `bp_value if isinstance(bp_value, dict) else
/// {key: bp_value}` — note raw sub-dicts are stored AS-IS (Python does
/// not emotion-format them here).
fn mbps_value<'py>(key: &str, bp_value: Bound<'py, PyAny>) -> EmotionVal<'py> {
    if bp_value.downcast::<PyDict>().is_ok() {
        EmotionVal::Raw(bp_value)
    } else {
        let mut single = EmotionMap::new();
        single.insert(key.to_owned(), EmotionVal::Raw(bp_value));
        EmotionVal::Map(single)
    }
}

/// Merge one `mbps` entry into `target` with `dict.update` semantics.
fn update_from_mbps_entry<'py>(
    target: &mut EmotionMap<'py>,
    sub: EmotionVal<'py>,
) -> Result<bool, PyReadError> {
    match sub {
        EmotionVal::Map(m) => {
            for (k, v) in m.entries {
                target.insert(k, v);
            }
        }
        EmotionVal::Raw(d) => {
            let Ok(dd) = d.downcast::<PyDict>() else {
                return Ok(false);
            };
            for (ik, iv) in dd.iter() {
                let Ok(iks) = py_str(&ik) else {
                    return Ok(false);
                };
                target.insert(iks, EmotionVal::Raw(iv));
            }
        }
    }
    Ok(true)
}

/// The transform itself. Mirrors `format_as_emotion` clause-for-clause;
/// returns `Fallback` on any structure outside the ported surface.
fn emotion_from_style<'py>(
    style: &Bound<'py, PyDict>,
    refs: &PyRefs<'py>,
) -> Result<EmotionOutcome<'py>, PyReadError> {
    let py = style.py();
    let mut out = EmotionMap::new();
    for (k_obj, value) in style.iter() {
        let Ok(orig_key) = py_str(&k_obj) else {
            return Ok(EmotionOutcome::Fallback);
        };
        let key = format_emotion_pseudo_selector(&orig_key);
        let is_breakpoints = value.is_instance(&refs.breakpoints_cls).unwrap_or(false);
        let is_list = value.downcast::<PyList>().is_ok();
        if is_breakpoints || is_list {
            // Build the media-query map in source order; EmotionMap::insert
            // reproduces the dict-comprehension's last-wins key semantics.
            let mut mbps = EmotionMap::new();
            if is_breakpoints {
                let Ok(d) = value.downcast::<PyDict>() else {
                    return Ok(EmotionOutcome::Fallback);
                };
                for (bp_obj, bp_value) in d.iter() {
                    let Ok(bp) = py_str(&bp_obj) else {
                        return Ok(EmotionOutcome::Fallback);
                    };
                    mbps.insert(media_query(&bp), mbps_value(&key, bp_value));
                }
            } else {
                // `[0, *breakpoints_values][i]` — read the mutable global
                // list each time so `set_breakpoints` overrides apply.
                let Ok(bvals_list) = refs.breakpoints_values.downcast::<PyList>() else {
                    return Ok(EmotionOutcome::Fallback);
                };
                let mut bvals: Vec<String> = Vec::with_capacity(bvals_list.len());
                for b in bvals_list.iter() {
                    let Ok(s) = py_str(&b) else {
                        return Ok(EmotionOutcome::Fallback);
                    };
                    bvals.push(s);
                }
                let list = value.downcast::<PyList>().unwrap();
                for (i, bp_value) in list.iter().enumerate() {
                    let bp_expr = if i == 0 {
                        "0"
                    } else if let Some(v) = bvals.get(i - 1) {
                        v.as_str()
                    } else {
                        // Python raises IndexError here; let it.
                        return Ok(EmotionOutcome::Fallback);
                    };
                    mbps.insert(media_query(bp_expr), mbps_value(&key, bp_value));
                }
            }
            if key.starts_with("&:") {
                out.insert(key, EmotionVal::Map(mbps));
            } else {
                for (mq, sub) in mbps.entries {
                    let Some(target) = out.setdefault_map(&mq) else {
                        return Ok(EmotionOutcome::Fallback);
                    };
                    if !update_from_mbps_entry(target, sub)? {
                        return Ok(EmotionOutcome::Fallback);
                    }
                }
            }
        } else if let Ok(nested) = value.downcast::<PyDict>() {
            match emotion_from_style(nested, refs)? {
                EmotionOutcome::Fallback => return Ok(EmotionOutcome::Fallback),
                // Empty nested dict: Python stores the `None` return.
                EmotionOutcome::Done(None) => {
                    out.insert(key, EmotionVal::Raw(py.None().into_bound(py)));
                }
                EmotionOutcome::Done(Some(m)) => out.insert(key, EmotionVal::Map(m)),
            }
        } else {
            out.insert(key, EmotionVal::Raw(value));
        }
    }
    Ok(EmotionOutcome::Done(if out.entries.is_empty() {
        None
    } else {
        Some(out)
    }))
}

/// Render an `EmotionMap` exactly like `render_style_object` renders the
/// Python emotion dict.
fn render_emotion_map(m: &EmotionMap<'_>, refs: &PyRefs<'_>) -> Result<String, PyReadError> {
    let mut entries: Vec<String> = Vec::with_capacity(m.entries.len());
    for (k, v) in &m.entries {
        let val = match v {
            EmotionVal::Raw(o) => render_style_value(o, refs)?,
            EmotionVal::Map(mm) => render_emotion_map(mm, refs)?,
        };
        entries.push(format!("[{}] : {}", encode_js_string(k), val));
    }
    Ok(format!("({{ {} }})", entries.join(", ")))
}

/// Render an emotion-style dict as the `({ ["k"] : v, ... })` object literal,
/// byte-identical to `LiteralVar.create(dict)._js_expr` but without the
/// per-entry `LiteralVar.create` round-trip into Python. `Style` already
/// stores values as `Var`s, so each value is a `Var` (→ `_js_expr`) or a
/// nested dict (pseudo-selectors / media queries); scalars are handled
/// defensively, and anything exotic falls back to `LiteralVar.create`.
fn render_style_object(d: &Bound<'_, PyDict>, refs: &PyRefs<'_>) -> Result<String, PyReadError> {
    let mut entries: Vec<String> = Vec::with_capacity(d.len());
    for (k, v) in d.iter() {
        let key = py_str(&k)?;
        let val = render_style_value(&v, refs)?;
        entries.push(format!("[{}] : {}", encode_js_string(&key), val));
    }
    Ok(format!("({{ {} }})", entries.join(", ")))
}

/// Render one emotion-dict value to JS, matching how `LiteralVar.create`
/// would render it as a nested object value.
fn render_style_value(v: &Bound<'_, PyAny>, refs: &PyRefs<'_>) -> Result<String, PyReadError> {
    let py = v.py();
    if v.is_none() {
        return Ok("null".to_owned());
    }
    if let Some(rv) = native_var(v, refs) {
        return Ok(rv.js_expr_str().to_owned());
    }
    if crate::pyo3_reader::is_var_value(v, &refs.var_cls).unwrap_or(false) {
        let expr = v
            .getattr(refs.attrs.js_expr.bind(py))
            .map_err(|source| PyReadError::Attr {
                attr: "Var._js_expr",
                source,
            })?;
        return py_str(&expr);
    }
    if let Ok(nested) = v.downcast::<PyDict>() {
        return render_style_object(nested, refs);
    }
    if v.is_instance_of::<pyo3::types::PyBool>() {
        if let Ok(b) = v.extract::<bool>() {
            return Ok(if b { "true" } else { "false" }.to_owned());
        }
    }
    if v.is_instance_of::<pyo3::types::PyInt>() {
        if let Ok(n) = v.extract::<i64>() {
            return Ok(n.to_string());
        }
    }
    if v.is_instance_of::<pyo3::types::PyFloat>() {
        if let Ok(f) = v.extract::<f64>() {
            return Ok(format_js_float(f));
        }
    }
    if v.is_instance_of::<pyo3::types::PyString>() {
        if let Ok(s) = v.extract::<String>() {
            return Ok(encode_js_string(&s));
        }
    }
    // Exotic value: defer to LiteralVar.create for an exact rendering.
    render_value_as_js(v, refs)
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
    let is_var = match crate::pyo3_reader::is_var_value(value, &refs.var_cls) {
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

    // Native Vars: read the Rust `VarData` struct directly — no
    // `_get_all_var_data` call (which clones the whole tree to wrap it
    // for Python) and no per-bucket getattr/iteration. Bucket contents
    // replicate the `PyVarData` getter surface exactly: `imports` pairs
    // come out empty (the generic path's `items()` call fails on the
    // tuple shape), `components` is always empty, `position` is always
    // `None`, and a dep's string form is its `js_expr`.
    let (hooks_syms, imports_pairs, deps_syms, components_syms, state_sym, position) =
        if let Some(rv) = native_var(value, refs) {
            let Some(vd) = rv.var_data_ref() else {
                return Ok(None);
            };
            let hooks: Vec<Symbol> = vd.hooks.iter().map(|h| intern(h)).collect();
            let deps: Vec<Symbol> = vd
                .deps
                .iter()
                .filter(|d| !d.js_expr().is_empty())
                .map(|d| intern(d.js_expr()))
                .collect();
            let state = if vd.state.is_empty() {
                Symbol::EMPTY
            } else {
                intern(&vd.state)
            };
            (hooks, Vec::new(), deps, Vec::new(), state, None)
        } else {
            let var_data =
                match refs.call_cached0(value, refs.attrs.m_get_all_var_data.bind(py), |c| {
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
            (
                pull_dict_keys(&var_data, "hooks"),
                pull_imports(&var_data, refs),
                pull_iter_symbols(&var_data, "deps"),
                pull_iter_symbols(&var_data, "components"),
                pull_state_symbol(&var_data, refs),
                pull_u8(&var_data, "position"),
            )
        };

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
    // Native Vars: state/hooks read straight off the Rust struct. The
    // embedded-components recursion below can't fire for them — the
    // `PyVarData.components` getter is always empty.
    if let Some(rv) = native_var(value, refs) {
        return Ok(rv
            .var_data_ref()
            .map(|vd| !vd.state.is_empty() || !vd.hooks.is_empty())
            .unwrap_or(false));
    }
    let is_var = match crate::pyo3_reader::is_var_value(value, &refs.var_cls) {
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
    // Native Vars: read the Rust-owned expression directly.
    if let Some(rv) = native_var(value, refs) {
        return Ok(rv.js_expr_str().to_owned());
    }
    let is_var = crate::pyo3_reader::is_var_value(value, &refs.var_cls).map_err(|source| {
        PyReadError::Attr {
            attr: "isinstance(value, Var)",
            source,
        }
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
                    let is_var =
                        crate::pyo3_reader::is_var_value(&contents, &refs.var_cls).unwrap_or(false);
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
#[allow(clippy::too_many_arguments)]
fn freeze_children_for<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    kind: NodeKind,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
    fold: bool,
) -> Result<(NodeIdx, NodeIdx), PyReadError> {
    match kind {
        // M2 fold note: the foreach body is FRESHLY rendered by
        // `render_component()` (not the legacy-folded `children[0]` ref),
        // so the legacy bytes never saw a folded foreach body — the fold
        // must not propagate into it.
        NodeKind::Foreach => freeze_foreach_body(py, component, self_idx, builder, refs, pending),
        // Match bodies alias `self.children` entries — the legacy fold
        // walked them, so the fold propagates.
        NodeKind::Match => {
            freeze_match_children(py, component, self_idx, builder, refs, pending, fold)
        }
        _ => freeze_children_iter(py, component, builder, refs, pending, fold),
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
    fold: bool,
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
        freeze_into_slot(py, &child, slot, builder, refs, pending, fold)?;
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
    self_idx: NodeIdx,
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
    // The body JSX references the IterTag's callback parameter names —
    // record them so the emitters declare matching arrow args instead of
    // fixed `(item, index)` placeholders.
    let arg_name = iter_tag
        .getattr("arg_var_name")
        .ok()
        .and_then(|v| py_str(&v).ok())
        .unwrap_or_default();
    let index_name = iter_tag
        .getattr("index_var_name")
        .ok()
        .and_then(|v| py_str(&v).ok())
        .unwrap_or_default();
    if !arg_name.is_empty() && !index_name.is_empty() {
        builder
            .snapshot_mut()
            .control_flow
            .foreach_args
            .insert(self_idx, (intern(&arg_name), intern(&index_name)));
    }
    let body = iter_tag
        .call_method0("render_component")
        .map_err(|source| PyReadError::Attr {
            attr: "IterTag.render_component()",
            source,
        })?;
    let start = builder.reserve();
    let end = builder.next_idx();
    // fold=false: this body is a fresh `render_fn` product the legacy
    // fold never touched (it folded the kept `children[0]` ref instead).
    freeze_into_slot(py, &body, start, builder, refs, pending, false)?;
    Ok((start, end))
}

/// `Match`: walk each entry of `match_cases` (`[case_a, …, body]`) plus
/// the optional `default` body. Records each `(case_expr → body_idx)`
/// pairing into `snapshot.control_flow.match_arms` and the default into
/// `match_default` so `emit_jsx_from_snapshot` can render the arms.
#[allow(clippy::too_many_arguments)]
fn freeze_match_children<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    self_idx: NodeIdx,
    builder: &mut SnapshotBuilder,
    refs: &PyRefs<'py>,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
    fold: bool,
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
                let body_idx = freeze_node(py, body, builder, refs, pending, fold)?;
                for case_obj in &entries[..entries.len() - 1] {
                    // `match_cases` entries are `(conditions_list, body)` —
                    // each condition gets its own `case` label (legacy
                    // `render_match_tag` iterates the group). Tolerate a
                    // bare condition for flat legacy shapes.
                    let mut push_cond = |cond: &Bound<'_, PyAny>,
                                         arms: &mut SmallVec<[(Symbol, NodeIdx); 2]>|
                     -> Result<(), PyReadError> {
                        let case_expr = render_value_as_js(cond, refs)?;
                        let case_sym = if case_expr.is_empty() {
                            intern("null")
                        } else {
                            intern(&case_expr)
                        };
                        arms.push((case_sym, body_idx));
                        Ok(())
                    };
                    if case_obj.downcast::<pyo3::types::PyList>().is_ok()
                        || case_obj.downcast::<pyo3::types::PyTuple>().is_ok()
                    {
                        let conds: Vec<Bound<'_, PyAny>> = case_obj
                            .iter()
                            .map_err(|source| PyReadError::Attr {
                                attr: "iter(Match conditions)",
                                source,
                            })?
                            .collect::<Result<Vec<_>, _>>()
                            .map_err(|source| PyReadError::Attr {
                                attr: "Match condition",
                                source,
                            })?;
                        for cond in &conds {
                            push_cond(cond, &mut arms)?;
                        }
                    } else {
                        push_cond(case_obj, &mut arms)?;
                    }
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
            let default_idx = freeze_node(py, &default, builder, refs, pending, fold)?;
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
    let is_var = crate::pyo3_reader::is_var_value(&contents, &refs.var_cls).map_err(|source| {
        PyReadError::Attr {
            attr: "isinstance(Bare.contents, Var)",
            source,
        }
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
    let inst_dict = instance_dict(component, refs);
    let alias = read_field(
        component,
        inst_dict.as_ref(),
        "alias",
        &refs.attrs.alias,
        refs,
    )
    .filter(|v| !v.is_none());
    let tag = read_field(component, inst_dict.as_ref(), "tag", &refs.attrs.tag, refs)
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
    let library = read_field(
        component,
        inst_dict.as_ref(),
        "library",
        &refs.attrs.library,
        refs,
    )
    .filter(|v| !v.is_none());
    // `_is_tag_in_global_scope` is a plain class attr (not a field) —
    // read_field resolves it Dynamic; keep the direct getattr.
    let py = component.py();
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
