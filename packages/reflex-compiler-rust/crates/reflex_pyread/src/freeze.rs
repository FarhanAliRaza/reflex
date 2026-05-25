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

use crate::pyo3_reader::{class_name, py_str, MemoModeCached, PyReadError, PyRefs};

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
    let Some(target_unbound) = refs.bun_imports.borrow().as_ref().map(|d| d.clone_ref(py))
    else {
        return;
    };
    let target = target_unbound.bind(py);
    for (lib_obj, items_obj) in imports_dict.iter() {
        let Ok(lib_py) = lib_obj.downcast::<PyString>() else { continue };
        let Ok(lib_str) = lib_py.to_str() else { continue };
        let new_lib = apply_alias_prefix(lib_str);
        let Ok(items_list) = items_obj.downcast::<pyo3::types::PyList>() else { continue };
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
    let Ok(prop_components) = component.call_method0("_get_components_in_props") else {
        return Ok(());
    };
    let Ok(it) = prop_components.iter() else {
        return Ok(());
    };
    for c in it.flatten() {
        let id = c.as_ptr() as usize;
        if !refs.imports_seen.borrow_mut().insert(id) {
            continue;
        }
        let Ok(imports_obj) = c.call_method0("_get_imports") else { continue };
        let Ok(imports_dict) = imports_obj.downcast::<pyo3::types::PyDict>() else { continue };
        merge_imports_dict_into_bun(py, &imports_dict, refs);
        // Recurse: prop-components can themselves have prop-components.
        merge_prop_components_imports(py, &c, refs)?;
    }
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
    let ty = component.get_type();
    let ty_key = ty.as_ptr() as usize;
    if let Some(cached) = refs.memo_mode_cache.borrow().get(&ty_key) {
        return Ok(*cached);
    }
    let (disposition_byte, recursive) = match component.getattr("_memoization_mode") {
        Ok(mode) if !mode.is_none() => {
            let disp_str = mode
                .getattr("disposition")
                .and_then(|d| d.getattr("value"))
                .and_then(|v| v.extract::<String>())
                .unwrap_or_else(|_| "stateful".to_owned());
            let recursive: bool = mode
                .getattr("recursive")
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
    let cls = class_name(component)?;
    let (kind, tag) = classify(component, &cls, refs)?;
    let style_key = read_qualname(component)?;

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

    // Stage 5: collect `_get_app_wrap_components()` per node and
    // queue each unique wrapper for deferred freezing. Cycle
    // protection: `SnapshotBuilder.mark_app_wrap_seen` dedupes by
    // `id(wrapper)` so shared wrapper instances (e.g. the radix
    // ColorMode provider returned by many children) freeze once.
    // The actual freeze happens after the page tree finishes — see
    // `freeze_component`'s drain loop — so page nodes' `children`
    // ranges stay contiguous within the page subtree.
    collect_app_wraps_into_queue(py, component, builder, pending)?;

    // Stage 1 per-node harvests. Each call is exactly once per Component;
    // the result is cached on the Component side (`_get_imports` /
    // `_get_hooks_*` decorate with `@functools.cache`-equivalent).
    let imports = read_imports_summary(py, component, refs)?;
    // PR7 follow-through: prop-Components (Components embedded in Var
    // values for props) aren't visited by the snapshot tree walk, but
    // their imports still need to land in the bun-install dict.
    // Visit them once per `id(component)`.
    merge_prop_components_imports(py, component, refs)?;
    let custom_code = read_custom_code(component)?;
    let dynamic_imports = read_dynamic_imports(component)?;
    let ref_name = read_ref_name(component)?;
    let hooks_internal = read_hooks_dict(component, "_get_hooks_internal")?;
    let hooks_user = read_hooks_user(component)?;

    // Stage 4 per-node render-time harvests. Element nodes capture
    // `Tag.props` (already camelCased + LiteralVar-wrapped) as
    // `(name, js_expr)` pairs, plus event-trigger handlers as
    // `(camelCasedTrigger, js_expr)` pairs. Other node kinds skip the
    // `_render()` call because their JSX shape doesn't carry props.
    let mut props_have_reactive_var = false;
    let mut vars_used: SmallVec<[VarDataRef; 4]> = SmallVec::new();
    let (rendered_props, event_callbacks, style, rename_props) = if matches!(kind, NodeKind::Element) {
        let props = read_rendered_props(
            component,
            refs,
            builder,
            &mut props_have_reactive_var,
            &mut vars_used,
        )?;
        let events = read_event_callbacks(component, refs)?;
        let style_sym = read_style(component, refs)?;
        let renames = read_rename_props(component)?;
        (props, events, style_sym, renames)
    } else {
        (SmallVec::new(), SmallVec::new(), Symbol::EMPTY, SmallVec::new())
    };
    let has_events = !event_callbacks.is_empty();

    // PR2 + PR7: Bare-contents reactivity + var-data dedup. The Bare
    // path doesn't go through `read_rendered_props`; mirror the same
    // checks on `component.contents` so the memoize decision picks up
    // Bare wrappers of state Vars AND the Var's metadata gets deduped
    // into `Snapshot.var_data`.
    let bare_has_reactive_contents = if cls == "Bare" {
        if let Ok(contents) = component.getattr("contents") {
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
    let mut out: SmallVec<[ImportEntry; 4]> = SmallVec::new();
    let imports_obj = match component.call_method0("_get_imports") {
        Ok(v) => v,
        Err(_) => return Ok(out),
    };
    let imports_dict: Bound<'_, PyDict> = match imports_obj.downcast_into() {
        Ok(d) => d,
        Err(_) => return Ok(out),
    };
    // PR7 follow-through: single `_get_imports()` call powers both
    // outputs. Merge into the bun-install accumulator here so the
    // arena entry doesn't need a separate `collect_all_imports`
    // tree walk. `imports_seen` dedup happens at the caller
    // (per-node freeze loop guarantees one call per snapshot node).
    if refs.imports_seen.borrow_mut().insert(component.as_ptr() as usize) {
        merge_imports_dict_into_bun(py, &imports_dict, refs);
    }
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
            let tag = entry.getattr("tag").ok().filter(|v| !v.is_none());
            let alias = entry.getattr("alias").ok().filter(|v| !v.is_none());
            let render = entry
                .getattr("render")
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
fn read_custom_code(component: &Bound<'_, PyAny>) -> Result<Symbol, PyReadError> {
    let v = match component.call_method0("_get_custom_code") {
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

/// Read `_get_dynamic_imports()`. Returns `str | None` per-component;
/// the snapshot stores it as a single-element SmallVec for uniformity
/// with the aggregate walk's output shape.
fn read_dynamic_imports(
    component: &Bound<'_, PyAny>,
) -> Result<SmallVec<[Symbol; 1]>, PyReadError> {
    let mut out: SmallVec<[Symbol; 1]> = SmallVec::new();
    let v = match component.call_method0("_get_dynamic_imports") {
        Ok(v) => v,
        Err(_) => return Ok(out),
    };
    if v.is_none() {
        return Ok(out);
    }
    // Be permissive: string is the documented shape but the method is
    // overrideable.  Strings become one entry; iterables become many.
    if let Ok(s) = py_str(&v) {
        if !s.is_empty() {
            out.push(intern(&s));
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
fn read_hooks_dict<const N: usize>(
    component: &Bound<'_, PyAny>,
    method: &str,
) -> Result<SmallVec<[HookEntry; N]>, PyReadError>
where
    [HookEntry; N]: smallvec::Array<Item = HookEntry>,
{
    let mut out: SmallVec<[HookEntry; N]> = SmallVec::new();
    let v = match component.call_method0(method) {
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
fn read_hooks_user(
    component: &Bound<'_, PyAny>,
) -> Result<SmallVec<[HookEntry; 1]>, PyReadError> {
    let mut out: SmallVec<[HookEntry; 1]> = SmallVec::new();
    // `_get_hooks()` → str | Var | None.
    if let Ok(v) = component.call_method0("_get_hooks") {
        if !v.is_none() {
            let s = py_str(&v).unwrap_or_default();
            if !s.is_empty() {
                out.push(HookEntry::new(intern(&s), 1));
            }
        }
    }
    // `_get_added_hooks()` → dict[str, VarData | None].
    if let Ok(v) = component.call_method0("_get_added_hooks") {
        if !v.is_none() {
            if let Ok(d) = v.downcast::<PyDict>() {
                for (k, vd) in d.iter() {
                    let code = py_str(&k)?;
                    if code.is_empty() {
                        continue;
                    }
                    let position = read_hook_position(&vd).unwrap_or(1);
                    out.push(HookEntry::new(intern(&code), position));
                }
            }
        }
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
    let mut raw_pairs: SmallVec<[(String, Symbol); 4]> = SmallVec::new();

    // ---- Dataclass fields via `Component.get_props()` ------------------
    if let Ok(prop_names_obj) = component.call_method0("get_props") {
        if let Ok(iter) = prop_names_obj.iter() {
            for name_res in iter {
                let name_obj = match name_res {
                    Ok(o) => o,
                    Err(_) => continue,
                };
                let raw: String = match py_str(&name_obj) {
                    Ok(s) => s,
                    Err(_) => continue,
                };
                // `class_` etc. — legacy strips a trailing `_` (Python
                // keyword escape) when emitting; the value lookup uses
                // the un-stripped attr name.
                let attr_name = raw.strip_suffix('_').unwrap_or(&raw).to_owned();
                let value_obj = match component.getattr(raw.as_str()) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                if value_obj.is_none() {
                    continue;
                }
                // PR2: piggy-back the reactive-Var check on the prop
                // walk so we don't traverse the prop list twice. Cost
                // is one `_get_all_var_data()` call per Var prop the
                // loop already touches (~1 µs after Python's
                // `@functools.cache` warms up).
                if !*reactive_out && var_has_reactive_data(&value_obj, refs)? {
                    *reactive_out = true;
                }
                // PR7: dedup-register the Var's metadata into
                // `Snapshot.var_data` (no-op for already-seen Vars).
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
        }
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
    if let Ok(custom) = component.getattr("custom_attrs") {
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
pub(crate) fn read_rename_props(
    component: &Bound<'_, PyAny>,
) -> Result<SmallVec<[(Symbol, Symbol); 1]>, PyReadError> {
    let mut out: SmallVec<[(Symbol, Symbol); 1]> = SmallVec::new();
    let rename_obj = match component.getattr("_rename_props") {
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
    let mut out: SmallVec<[(Symbol, Symbol); 2]> = SmallVec::new();
    let triggers = match component.getattr("event_triggers") {
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
fn read_style(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<Symbol, PyReadError> {
    let style_obj = match component.call_method0("_get_style") {
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
    let var_data = match value.call_method0("_get_all_var_data") {
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
    let imports_pairs = pull_imports(&var_data);
    let deps_syms = pull_iter_symbols(&var_data, "deps");
    let components_syms = pull_iter_symbols(&var_data, "components");
    let state_sym = pull_state_symbol(&var_data);
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

fn pull_imports(var_data: &Bound<'_, PyAny>) -> Vec<(Symbol, Symbol)> {
    let mut out = Vec::new();
    let Ok(obj) = var_data.getattr("imports") else { return out };
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
                let Ok(tup) = kv.downcast::<pyo3::types::PyTuple>() else { continue };
                if tup.len() != 2 {
                    continue;
                }
                let Ok(module_obj) = tup.get_item(0) else { continue };
                let Ok(module) = py_str(&module_obj) else { continue };
                let Ok(items) = tup.get_item(1) else { continue };
                if items.is_none() {
                    continue;
                }
                if let Ok(items_iter) = items.iter() {
                    for iv in items_iter.flatten() {
                        let name = iv
                            .getattr("tag")
                            .ok()
                            .filter(|v| !v.is_none())
                            .and_then(|v| py_str(&v).ok())
                            .or_else(|| {
                                iv.getattr("alias")
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

fn pull_state_symbol(var_data: &Bound<'_, PyAny>) -> Symbol {
    let Ok(obj) = var_data.getattr("state") else { return Symbol::EMPTY };
    if obj.is_none() {
        return Symbol::EMPTY;
    }
    let Ok(s) = py_str(&obj) else { return Symbol::EMPTY };
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
    obj.getattr("value").ok().and_then(|v| v.extract::<u8>().ok())
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
fn var_has_reactive_data(
    value: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<bool, PyReadError> {
    let is_var = match value.is_instance(&refs.var_cls) {
        Ok(b) => b,
        Err(_) => return Ok(false),
    };
    if !is_var {
        return Ok(false);
    }
    let var_data = match value.call_method0("_get_all_var_data") {
        Ok(v) => v,
        Err(_) => return Ok(false),
    };
    if var_data.is_none() {
        return Ok(false);
    }
    // `state` is a string (state class identifier or ""); non-empty
    // means reactive.
    if let Ok(state) = var_data.getattr("state") {
        if !state.is_none() {
            if let Ok(s) = py_str(&state) {
                if !s.is_empty() {
                    return Ok(true);
                }
            }
        }
    }
    // `hooks` is a dict-like; non-empty means reactive.
    if let Ok(hooks) = var_data.getattr("hooks") {
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
    if let Ok(components) = var_data.getattr("components") {
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
fn subtree_has_reactive_data(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
    depth: u8,
) -> Result<bool, PyReadError> {
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
    if let Ok(triggers) = component.getattr("event_triggers") {
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
    if let Ok(children) = component.getattr("children") {
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
fn render_value_as_js(
    value: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<String, PyReadError> {
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
            .getattr("_js_expr")
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
            return Ok(if b { "true".to_owned() } else { "false".to_owned() });
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
    if let Ok(expr) = wrapped.getattr("_js_expr") {
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
        assert_eq!(format_library_name_str("@radix-ui/themes@3.3.0"), "@radix-ui/themes");
        assert_eq!(format_library_name_str("react@18.2.0"), "react");
        assert_eq!(format_library_name_str("react"), "react");
        assert_eq!(format_library_name_str("@radix-ui/themes"), "@radix-ui/themes");
        assert_eq!(format_library_name_str("https://cdn.example/x@1"), "https://cdn.example/x@1");
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

/// Walk `component._get_app_wrap_components()` and queue each unique
/// wrapper for deferred freezing. The wrapper subtree is appended to
/// the arena AFTER the page tree finishes — see `freeze_component`'s
/// drain loop. Cycle protection: `SnapshotBuilder.mark_app_wrap_seen`
/// dedupes by `id(wrapper)` so shared instances (the radix ColorMode
/// provider returned by many children) freeze once.
fn collect_app_wraps_into_queue<'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    builder: &mut SnapshotBuilder,
    pending: &mut Vec<(i32, String, Py<PyAny>)>,
) -> Result<(), PyReadError> {
    let wraps_obj = match component.call_method0("_get_app_wrap_components") {
        Ok(v) => v,
        Err(_) => return Ok(()),
    };
    if wraps_obj.is_none() {
        return Ok(());
    }
    let Ok(d) = wraps_obj.downcast::<PyDict>() else {
        return Ok(());
    };
    for (key_obj, value_obj) in d.iter() {
        let Ok(tup) = key_obj.downcast::<pyo3::types::PyTuple>() else {
            continue;
        };
        if tup.len() != 2 {
            continue;
        }
        let priority: i32 = match tup
            .get_item(0)
            .ok()
            .and_then(|v| v.extract::<i32>().ok())
        {
            Some(p) => p,
            None => continue,
        };
        let name = match tup.get_item(1).ok().and_then(|v| py_str(&v).ok()) {
            Some(n) if !n.is_empty() => n,
            _ => continue,
        };
        let pyid = value_obj.as_ptr() as usize;
        if !builder.mark_app_wrap_seen(pyid) {
            continue;
        }
        pending.push((priority, name, value_obj.unbind()));
    }
    let _ = py;
    Ok(())
}

/// Populate `snapshot.control_flow` for kinds that carry sparse
/// side-table data (Text content, Expr value, Cond.test, Foreach.iter,
/// Match.value, Memoize.key). Match arms (case → body index) are
/// deferred to a follow-on Stage 5 sub-task because they need
/// per-arm pairing with the just-pushed child indices.
fn populate_control_flow<'py>(
    _py: Python<'py>,
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
            if let Ok(contents) = component.getattr("contents") {
                if !contents.is_none() {
                    let is_var = contents
                        .is_instance(&refs.var_cls)
                        .unwrap_or(false);
                    let s = if is_var {
                        contents
                            .getattr("_js_expr")
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
            if let Ok(contents) = component.getattr("contents") {
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
            if let Ok(cond) = component.getattr("cond") {
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
            if let Ok(iterable) = component.getattr("iterable") {
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
            if let Ok(cond) = component.getattr("cond") {
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
    let children_obj = match component.getattr("children") {
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
        read_tag(component)?
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
fn classify_bare(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<NodeKind, PyReadError> {
    let contents = match component.getattr("contents") {
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
    if let Ok(expr_obj) = contents.getattr("_js_expr") {
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
fn read_tag(component: &Bound<'_, PyAny>) -> Result<Symbol, PyReadError> {
    let alias = component.getattr("alias").ok().filter(|v| !v.is_none());
    let tag = component.getattr("tag").ok().filter(|v| !v.is_none());
    let raw_name = match (alias, tag) {
        (Some(a), _) => py_str(&a)?,
        (None, Some(t)) => py_str(&t)?,
        _ => return Ok(Symbol::EMPTY),
    };
    let trimmed = raw_name.trim_matches('"').to_owned();
    if trimmed.is_empty() {
        return Ok(Symbol::EMPTY);
    }
    let library = component.getattr("library").ok().filter(|v| !v.is_none());
    let is_global_scope = match component.getattr("_is_tag_in_global_scope") {
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
fn read_qualname(component: &Bound<'_, PyAny>) -> Result<Symbol, PyReadError> {
    let ty = component.get_type();
    if let Ok(q) = ty.getattr("__qualname__") {
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
        // exercises it under a real PyO3 component).
        let _ = read_qualname as fn(&Bound<'_, PyAny>) -> Result<Symbol, PyReadError>;
    }
}
