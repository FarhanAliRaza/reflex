//! `build_snapshot_from_wire` — reconstruct a [`Snapshot`] from the plain
//! Python dict produced by [`crate::snapshot_dump::snapshot_to_pydict`].
//!
//! This is the exact inverse of the dump: every `Symbol` is re-interned
//! from its string, every side table is rebuilt, and the post-freeze
//! fields the dump captured (`flags`, including `PROPAGATES_HOOKS`, and
//! `subtree_hash`) are restored verbatim rather than recomputed. So
//! `build_snapshot_from_wire(snapshot_to_pydict(s))` reproduces `s`
//! field-for-field, and `compile_page_from_arena(dump_snapshot(c))` emits
//! byte-identically to the freeze path.
//!
//! `node_pyids` is not carried in the wire dict (it is `id()`-based and
//! feeds nothing downstream of emit); it is rebuilt as a zero vector of
//! the right length so the `nodes` / `node_pyids` length invariant holds.
//! `memo_bodies` / `memo_dedup` are left empty — the snapshot is
//! pre-memoize, exactly as `freeze_component` returns it, and
//! `memoize_arena_pass` fills them downstream.

use std::collections::HashMap;
use std::ops::Range;

use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use smallvec::SmallVec;

use reflex_intern::{intern, Symbol};
use reflex_ir::{
    AppWrap, ControlFlowExtras, HookEntry, ImportEntry, NodeFlags, NodeKind, NodeSnapshot,
    Snapshot, VarDataEntry, VarDataRef,
};

/// Fetch a required dict key, erroring with its name if absent.
fn req<'py>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    d.get_item(key)?
        .ok_or_else(|| PyKeyError::new_err(format!("snapshot wire dict missing key {key:?}")))
}

/// Extract `d[key]` into a Rust value of the inferred type.
fn get<'py, T: FromPyObject<'py>>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<T> {
    req(d, key)?.extract()
}

/// Map a kind discriminant back to its `NodeKind`.
fn kind_from_u8(k: u8) -> PyResult<NodeKind> {
    Ok(match k {
        0 => NodeKind::Element,
        1 => NodeKind::Text,
        2 => NodeKind::Foreach,
        3 => NodeKind::Cond,
        4 => NodeKind::Match,
        5 => NodeKind::Memoize,
        6 => NodeKind::Fragment,
        7 => NodeKind::Expr,
        8 => NodeKind::MemoizeWrapper,
        _ => return Err(PyValueError::new_err(format!("unknown NodeKind {k}"))),
    })
}

/// Rebuild a `HashMap<u32, Symbol>` side table from `{idx: str}`.
fn sym_map(raw: HashMap<u32, String>) -> HashMap<u32, Symbol> {
    raw.into_iter().map(|(k, v)| (k, intern(&v))).collect()
}

/// Reconstruct one `NodeSnapshot` from its dict.
fn node_from_pydict(d: &Bound<'_, PyDict>) -> PyResult<NodeSnapshot> {
    let kind = kind_from_u8(get::<u8>(d, "kind")?)?;
    let tag = intern(&get::<String>(d, "tag")?);
    let style_key = intern(&get::<String>(d, "style_key")?);
    let style = intern(&get::<String>(d, "style")?);

    let rendered_props: SmallVec<[(Symbol, Symbol); 4]> =
        get::<Vec<(String, String)>>(d, "rendered_props")?
            .iter()
            .map(|(a, b)| (intern(a), intern(b)))
            .collect();
    let event_callbacks: SmallVec<[(Symbol, Symbol); 2]> =
        get::<Vec<(String, String)>>(d, "event_callbacks")?
            .iter()
            .map(|(a, b)| (intern(a), intern(b)))
            .collect();

    let imports: SmallVec<[ImportEntry; 4]> = get::<Vec<(String, String)>>(d, "imports")?
        .iter()
        .map(|(m, n)| ImportEntry::new(intern(m), intern(n)))
        .collect();

    let hooks_internal: SmallVec<[HookEntry; 2]> = get::<Vec<(String, u32)>>(d, "hooks_internal")?
        .into_iter()
        .map(|(code, pos)| HookEntry::new(intern(&code), pos as u8))
        .collect();
    let hooks_user: SmallVec<[HookEntry; 1]> = get::<Vec<(String, u32)>>(d, "hooks_user")?
        .into_iter()
        .map(|(code, pos)| HookEntry::new(intern(&code), pos as u8))
        .collect();

    let custom_code = intern(&get::<String>(d, "custom_code")?);

    let dynamic_imports: SmallVec<[Symbol; 1]> = get::<Vec<String>>(d, "dynamic_imports")?
        .iter()
        .map(|s| intern(s))
        .collect();

    let ref_name = intern(&get::<String>(d, "ref_name")?);

    let vars_used: SmallVec<[VarDataRef; 4]> = get::<Vec<Option<u32>>>(d, "vars_used")?
        .into_iter()
        .map(|o| match o {
            Some(i) => VarDataRef(i),
            None => VarDataRef::NONE,
        })
        .collect();

    let (cstart, cend) = get::<(u32, u32)>(d, "children")?;
    let flags = NodeFlags::from_bits(get::<u16>(d, "flags")?);
    let subtree_hash = get::<u64>(d, "subtree_hash")?;

    Ok(NodeSnapshot {
        kind,
        tag,
        style_key,
        style,
        rendered_props,
        event_callbacks,
        imports,
        hooks_internal,
        hooks_user,
        custom_code,
        dynamic_imports,
        ref_name,
        vars_used,
        children: cstart..cend,
        flags,
        subtree_hash,
    })
}

/// Reconstruct the `ControlFlowExtras` side tables.
fn control_flow_from_pydict(d: &Bound<'_, PyDict>) -> PyResult<ControlFlowExtras> {
    let arms_raw = get::<HashMap<u32, Vec<(String, u32)>>>(d, "match_arms")?;
    let match_arms = arms_raw
        .into_iter()
        .map(|(k, arms)| {
            let v: SmallVec<[(Symbol, u32); 2]> =
                arms.iter().map(|(e, b)| (intern(e), *b)).collect();
            (k, v)
        })
        .collect();

    Ok(ControlFlowExtras {
        text_value: sym_map(get(d, "text_value")?),
        cond_test: sym_map(get(d, "cond_test")?),
        foreach_iter: sym_map(get(d, "foreach_iter")?),
        match_value: sym_map(get(d, "match_value")?),
        expr_value: sym_map(get(d, "expr_value")?),
        memo_key: sym_map(get(d, "memo_key")?),
        match_arms,
        match_default: get::<HashMap<u32, u32>>(d, "match_default")?,
    })
}

/// Reconstruct one `VarDataEntry` from its dict.
fn var_data_entry_from_pydict(d: &Bound<'_, PyDict>) -> PyResult<VarDataEntry> {
    let pair = |key| -> PyResult<Range<u32>> {
        let (s, e) = get::<(u32, u32)>(d, key)?;
        Ok(s..e)
    };
    Ok(VarDataEntry {
        hooks: pair("hooks")?,
        imports: pair("imports")?,
        deps: pair("deps")?,
        components: pair("components")?,
        state: intern(&get::<String>(d, "state")?),
        position: get::<u32>(d, "position")? as u8,
    })
}

/// Build a [`Snapshot`] from the wire dict produced by `snapshot_to_pydict`.
pub fn build_snapshot_from_wire(dump: &Bound<'_, PyDict>) -> PyResult<Snapshot> {
    let mut snap = Snapshot::default();
    snap.root = get::<u32>(dump, "root")?;

    let node_dicts: Vec<Bound<PyDict>> = req(dump, "nodes")?
        .downcast_into::<pyo3::types::PyList>()
        .map_err(|e| PyValueError::new_err(format!("nodes must be a list: {e}")))?
        .iter()
        .map(|item| {
            item.downcast_into::<PyDict>()
                .map_err(|e| PyValueError::new_err(format!("node must be a dict: {e}")))
        })
        .collect::<PyResult<_>>()?;
    snap.nodes = node_dicts
        .iter()
        .map(node_from_pydict)
        .collect::<PyResult<_>>()?;
    snap.node_pyids = vec![0usize; snap.nodes.len()];

    // var_data table + dense backings.
    let var_data_dicts: Vec<Bound<PyDict>> = req(dump, "var_data")?
        .downcast_into::<pyo3::types::PyList>()
        .map_err(|e| PyValueError::new_err(format!("var_data must be a list: {e}")))?
        .iter()
        .map(|item| {
            item.downcast_into::<PyDict>()
                .map_err(|e| PyValueError::new_err(format!("var_data entry must be a dict: {e}")))
        })
        .collect::<PyResult<_>>()?;
    snap.var_data = var_data_dicts
        .iter()
        .map(var_data_entry_from_pydict)
        .collect::<PyResult<_>>()?;

    snap.var_hooks = get::<Vec<String>>(dump, "var_hooks")?
        .iter()
        .map(|s| intern(s))
        .collect();
    snap.var_imports = get::<Vec<(String, String)>>(dump, "var_imports")?
        .iter()
        .map(|(m, n)| (intern(m), intern(n)))
        .collect();
    snap.var_deps = get::<Vec<String>>(dump, "var_deps")?
        .iter()
        .map(|s| intern(s))
        .collect();
    snap.var_components = get::<Vec<String>>(dump, "var_components")?
        .iter()
        .map(|s| intern(s))
        .collect();

    let cf = req(dump, "control_flow")?
        .downcast_into::<PyDict>()
        .map_err(|e| PyValueError::new_err(format!("control_flow must be a dict: {e}")))?;
    snap.control_flow = control_flow_from_pydict(&cf)?;

    snap.wrap_redirects = get::<HashMap<u32, u32>>(dump, "wrap_redirects")?;

    let app_wrap_dicts: Vec<Bound<PyDict>> = req(dump, "app_wraps")?
        .downcast_into::<pyo3::types::PyList>()
        .map_err(|e| PyValueError::new_err(format!("app_wraps must be a list: {e}")))?
        .iter()
        .map(|item| {
            item.downcast_into::<PyDict>()
                .map_err(|e| PyValueError::new_err(format!("app_wrap must be a dict: {e}")))
        })
        .collect::<PyResult<_>>()?;
    snap.app_wraps = app_wrap_dicts
        .iter()
        .map(|w| {
            Ok(AppWrap {
                sort_key: get::<i32>(w, "sort_key")?,
                name: intern(&get::<String>(w, "name")?),
                root: get::<u32>(w, "root")?,
            })
        })
        .collect::<PyResult<_>>()?;

    snap.add_custom_code_extra = get::<HashMap<u32, Vec<String>>>(dump, "add_custom_code_extra")?
        .into_iter()
        .map(|(k, v)| (k, v.iter().map(|s| intern(s)).collect()))
        .collect();
    snap.special_props = get::<HashMap<u32, Vec<String>>>(dump, "special_props")?
        .into_iter()
        .map(|(k, v)| (k, v.iter().map(|s| intern(s)).collect()))
        .collect();
    snap.rename_props = get::<HashMap<u32, Vec<(String, String)>>>(dump, "rename_props")?
        .into_iter()
        .map(|(k, v)| (k, v.iter().map(|(a, b)| (intern(a), intern(b))).collect()))
        .collect();
    snap.app_style_map = get::<HashMap<String, String>>(dump, "app_style_map")?
        .into_iter()
        .map(|(k, v)| (intern(&k), intern(&v)))
        .collect();

    // page_meta
    let pm = req(dump, "page_meta")?
        .downcast_into::<PyDict>()
        .map_err(|e| PyValueError::new_err(format!("page_meta must be a dict: {e}")))?;
    snap.page_meta.schema_version = get::<u32>(&pm, "schema_version")?;
    snap.page_meta.route = intern(&get::<String>(&pm, "route")?);
    snap.page_meta.title = intern(&get::<String>(&pm, "title")?);
    snap.page_meta.meta = get::<Vec<(String, String)>>(&pm, "meta")?
        .iter()
        .map(|(k, v)| (intern(k), intern(v)))
        .collect();

    Ok(snap)
}
