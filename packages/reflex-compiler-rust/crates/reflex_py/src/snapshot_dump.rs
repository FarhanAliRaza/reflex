//! `snapshot_to_pydict` — serialize a frozen [`Snapshot`] into a plain
//! Python dict.
//!
//! This is the **parity-oracle vehicle** for the Python-freezer work
//! (see the refine-local plan, PR A). The wire format the Python gatherer
//! will eventually ship is a *raw, pre-render* bundle; this dump, by
//! contrast, is the *post-render* snapshot. Comparing the dumps of two
//! snapshots —
//! `dump_snapshot(build_from_wire(gather(c))) == dump_snapshot(freeze(c))`
//! — is how the gather path proves byte-parity with the Rust freeze walk
//! without re-implementing rendering in Python.
//!
//! The dump is intentionally lossless over every emit-relevant field of
//! `Snapshot` / `NodeSnapshot` / the side tables. `Symbol`s resolve to
//! their interned strings (`Symbol::EMPTY` → `""`). `node_pyids` is
//! deliberately omitted: it stores `id(component)` values that vary
//! run-to-run and feed nothing downstream of emit, so including it would
//! make the dump nondeterministic without adding oracle value.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

use reflex_intern::Symbol;
use reflex_ir::{ControlFlowExtras, HookEntry, NodeSnapshot, Snapshot, VarDataEntry};

/// Resolve an interned symbol to its string. Unknown symbols (which
/// should not occur for a snapshot built by the in-process interner)
/// degrade to the empty string rather than panicking.
#[inline]
fn sym(s: Symbol) -> &'static str {
    reflex_intern::resolve(s).unwrap_or("")
}

/// Build a `(u32, u32)` Python tuple for a half-open index range.
fn range_pair<'py>(py: Python<'py>, r: &std::ops::Range<u32>) -> Bound<'py, PyTuple> {
    PyTuple::new_bound(py, [r.start, r.end])
}

/// Serialize one `NodeSnapshot` into a dict mirroring its fields.
fn node_to_pydict<'py>(py: Python<'py>, node: &NodeSnapshot) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("kind", node.kind as u8)?;
    d.set_item("tag", sym(node.tag))?;
    d.set_item("style_key", sym(node.style_key))?;
    d.set_item("style", sym(node.style))?;

    let rendered_props: Vec<Bound<PyTuple>> = node
        .rendered_props
        .iter()
        .map(|(k, v)| PyTuple::new_bound(py, [sym(*k), sym(*v)]))
        .collect();
    d.set_item("rendered_props", PyList::new_bound(py, rendered_props))?;

    let event_callbacks: Vec<Bound<PyTuple>> = node
        .event_callbacks
        .iter()
        .map(|(k, v)| PyTuple::new_bound(py, [sym(*k), sym(*v)]))
        .collect();
    d.set_item("event_callbacks", PyList::new_bound(py, event_callbacks))?;

    let imports: Vec<Bound<PyTuple>> = node
        .imports
        .iter()
        .map(|e| PyTuple::new_bound(py, [sym(e.module), sym(e.name)]))
        .collect();
    d.set_item("imports", PyList::new_bound(py, imports))?;

    d.set_item("hooks_internal", hooks_to_pylist(py, &node.hooks_internal))?;
    d.set_item("hooks_user", hooks_to_pylist(py, &node.hooks_user))?;

    d.set_item("custom_code", sym(node.custom_code))?;

    let dynamic_imports: Vec<&str> = node.dynamic_imports.iter().map(|s| sym(*s)).collect();
    d.set_item("dynamic_imports", PyList::new_bound(py, dynamic_imports))?;

    d.set_item("ref_name", sym(node.ref_name))?;

    let vars_used: Vec<PyObject> = node
        .vars_used
        .iter()
        .map(|r| {
            if r.is_none() {
                py.None()
            } else {
                r.0.into_py(py)
            }
        })
        .collect();
    d.set_item("vars_used", PyList::new_bound(py, vars_used))?;

    d.set_item("children", range_pair(py, &node.children))?;
    d.set_item("flags", node.flags.bits())?;
    d.set_item("subtree_hash", node.subtree_hash)?;
    Ok(d)
}

/// Serialize a `HookEntry` SmallVec into a list of `(code, position)` tuples.
fn hooks_to_pylist<'py>(py: Python<'py>, hooks: &[HookEntry]) -> Bound<'py, PyList> {
    let items: Vec<Bound<PyTuple>> = hooks
        .iter()
        .map(|h| {
            PyTuple::new_bound(
                py,
                [sym(h.code).into_py(py), (h.position as u32).into_py(py)],
            )
        })
        .collect();
    PyList::new_bound(py, items)
}

/// Serialize one `VarDataEntry` (ranges into the dense backings + state).
fn var_data_entry_to_pydict<'py>(
    py: Python<'py>,
    e: &VarDataEntry,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("hooks", range_pair(py, &e.hooks))?;
    d.set_item("imports", range_pair(py, &e.imports))?;
    d.set_item("deps", range_pair(py, &e.deps))?;
    d.set_item("components", range_pair(py, &e.components))?;
    d.set_item("state", sym(e.state))?;
    d.set_item("position", e.position as u32)?;
    Ok(d)
}

/// Serialize the sparse `ControlFlowExtras` side tables, each keyed by
/// `NodeIdx`. Keys are emitted sorted so the dump is stable to read.
fn control_flow_to_pydict<'py>(
    py: Python<'py>,
    cf: &ControlFlowExtras,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);

    d.set_item("text_value", sym_map_to_pydict(py, &cf.text_value)?)?;
    d.set_item("cond_test", sym_map_to_pydict(py, &cf.cond_test)?)?;
    d.set_item("foreach_iter", sym_map_to_pydict(py, &cf.foreach_iter)?)?;
    d.set_item("match_value", sym_map_to_pydict(py, &cf.match_value)?)?;
    d.set_item("expr_value", sym_map_to_pydict(py, &cf.expr_value)?)?;
    d.set_item("memo_key", sym_map_to_pydict(py, &cf.memo_key)?)?;

    // match_arms: idx -> [(case_expr, body_idx), ...]
    let arms = PyDict::new_bound(py);
    let mut keys: Vec<u32> = cf.match_arms.keys().copied().collect();
    keys.sort_unstable();
    for k in keys {
        let pairs: Vec<Bound<PyTuple>> = cf.match_arms[&k]
            .iter()
            .map(|(expr, body)| PyTuple::new_bound(py, [sym(*expr).into_py(py), body.into_py(py)]))
            .collect();
        arms.set_item(k, PyList::new_bound(py, pairs))?;
    }
    d.set_item("match_arms", arms)?;

    // match_default: idx -> body_idx
    let default = PyDict::new_bound(py);
    let mut dkeys: Vec<u32> = cf.match_default.keys().copied().collect();
    dkeys.sort_unstable();
    for k in dkeys {
        default.set_item(k, cf.match_default[&k])?;
    }
    d.set_item("match_default", default)?;

    Ok(d)
}

/// Serialize a `HashMap<NodeIdx, Symbol>` as `{idx: str}`, keys sorted.
fn sym_map_to_pydict<'py>(
    py: Python<'py>,
    map: &std::collections::HashMap<u32, Symbol>,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    let mut keys: Vec<u32> = map.keys().copied().collect();
    keys.sort_unstable();
    for k in keys {
        d.set_item(k, sym(map[&k]))?;
    }
    Ok(d)
}

/// Serialize a complete [`Snapshot`] into a plain Python dict.
///
/// The result is deterministic for a given snapshot (no `id()`s, sorted
/// side-table keys) and lossless over every field emit / memoize read.
pub fn snapshot_to_pydict<'py>(py: Python<'py>, snap: &Snapshot) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("root", snap.root)?;

    let nodes: PyResult<Vec<Bound<PyDict>>> =
        snap.nodes.iter().map(|n| node_to_pydict(py, n)).collect();
    d.set_item("nodes", PyList::new_bound(py, nodes?))?;

    let var_data: PyResult<Vec<Bound<PyDict>>> = snap
        .var_data
        .iter()
        .map(|e| var_data_entry_to_pydict(py, e))
        .collect();
    d.set_item("var_data", PyList::new_bound(py, var_data?))?;

    let var_hooks: Vec<&str> = snap.var_hooks.iter().map(|s| sym(*s)).collect();
    d.set_item("var_hooks", PyList::new_bound(py, var_hooks))?;

    let var_imports: Vec<Bound<PyTuple>> = snap
        .var_imports
        .iter()
        .map(|(m, n)| PyTuple::new_bound(py, [sym(*m), sym(*n)]))
        .collect();
    d.set_item("var_imports", PyList::new_bound(py, var_imports))?;

    let var_deps: Vec<&str> = snap.var_deps.iter().map(|s| sym(*s)).collect();
    d.set_item("var_deps", PyList::new_bound(py, var_deps))?;

    let var_components: Vec<&str> = snap.var_components.iter().map(|s| sym(*s)).collect();
    d.set_item("var_components", PyList::new_bound(py, var_components))?;

    d.set_item(
        "control_flow",
        control_flow_to_pydict(py, &snap.control_flow)?,
    )?;

    // wrap_redirects: idx -> idx (sorted keys).
    let wrap = PyDict::new_bound(py);
    let mut wkeys: Vec<u32> = snap.wrap_redirects.keys().copied().collect();
    wkeys.sort_unstable();
    for k in wkeys {
        wrap.set_item(k, snap.wrap_redirects[&k])?;
    }
    d.set_item("wrap_redirects", wrap)?;

    // app_wraps: [{sort_key, name, root}, ...]
    let app_wraps: PyResult<Vec<Bound<PyDict>>> = snap
        .app_wraps
        .iter()
        .map(|w| {
            let wd = PyDict::new_bound(py);
            wd.set_item("sort_key", w.sort_key)?;
            wd.set_item("name", sym(w.name))?;
            wd.set_item("root", w.root)?;
            Ok(wd)
        })
        .collect();
    d.set_item("app_wraps", PyList::new_bound(py, app_wraps?))?;

    // add_custom_code_extra: idx -> [str, ...]
    let extra = PyDict::new_bound(py);
    let mut ekeys: Vec<u32> = snap.add_custom_code_extra.keys().copied().collect();
    ekeys.sort_unstable();
    for k in ekeys {
        let v: Vec<&str> = snap.add_custom_code_extra[&k]
            .iter()
            .map(|s| sym(*s))
            .collect();
        extra.set_item(k, PyList::new_bound(py, v))?;
    }
    d.set_item("add_custom_code_extra", extra)?;

    // special_props: idx -> [str, ...]
    let special = PyDict::new_bound(py);
    let mut skeys: Vec<u32> = snap.special_props.keys().copied().collect();
    skeys.sort_unstable();
    for k in skeys {
        let v: Vec<&str> = snap.special_props[&k].iter().map(|s| sym(*s)).collect();
        special.set_item(k, PyList::new_bound(py, v))?;
    }
    d.set_item("special_props", special)?;

    // rename_props: idx -> [(from, to), ...]
    let rename = PyDict::new_bound(py);
    let mut rkeys: Vec<u32> = snap.rename_props.keys().copied().collect();
    rkeys.sort_unstable();
    for k in rkeys {
        let pairs: Vec<Bound<PyTuple>> = snap.rename_props[&k]
            .iter()
            .map(|(f, t)| PyTuple::new_bound(py, [sym(*f), sym(*t)]))
            .collect();
        rename.set_item(k, PyList::new_bound(py, pairs))?;
    }
    d.set_item("rename_props", rename)?;

    // app_style_map: qualname -> style_js (sorted by qualname).
    let app_style = PyDict::new_bound(py);
    let mut akeys: Vec<Symbol> = snap.app_style_map.keys().copied().collect();
    akeys.sort_unstable_by_key(|s| sym(*s));
    for k in akeys {
        app_style.set_item(sym(k), sym(snap.app_style_map[&k]))?;
    }
    d.set_item("app_style_map", app_style)?;

    // page_meta
    let pm = PyDict::new_bound(py);
    pm.set_item("schema_version", snap.page_meta.schema_version)?;
    pm.set_item("route", sym(snap.page_meta.route))?;
    pm.set_item("title", sym(snap.page_meta.title))?;
    let meta: Vec<Bound<PyTuple>> = snap
        .page_meta
        .meta
        .iter()
        .map(|(k, v)| PyTuple::new_bound(py, [sym(*k), sym(*v)]))
        .collect();
    pm.set_item("meta", PyList::new_bound(py, meta))?;
    d.set_item("page_meta", pm)?;

    Ok(d)
}
