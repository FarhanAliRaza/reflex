//! `CompilerSession` — the real PyO3 entry point. See plan §3.4, D4.
//!
//! The Python side keeps a long-lived `CompilerSession` instance across
//! reloads. Each `compile_app(...)` call ships per-page msgpack blobs plus
//! the theme/global-state/plugin-manifest blobs; Rust parses, emits, and
//! returns a `CompiledOutput` carrying `{path: bytes}` for the Python side
//! to write.
//!
//! Salsa caching lands in D5. Until then every call rebuilds — the
//! `content_hash` ferried over the wire is recorded but unused.

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyList, PyString, PyTuple};

use reflex_codegen::harvest::{collect_custom_code, collect_dynamic_imports};
use reflex_codegen::hooks_emit::{render_hooks_rx_memo, render_hooks_unfiltered};
use reflex_codegen::{
    emit_app_root_module, emit_context_module, emit_document_root_module,
    emit_jsx_compact_from_snapshot, emit_memo_index, emit_memo_module_from_snapshot,
    emit_page_module_from_snapshot, emit_stateful_pages_json, emit_styles_root, emit_theme_module,
    memoize_arena_pass, CodeBuffer,
};
use reflex_db::CompilerDb;
use reflex_intern::{intern, resolve_unchecked, Symbol};
use reflex_vars::RustVar;
use reflex_pyread::{
    collect_all_imports as pyread_collect_all_imports,
    collect_all_imports_into as pyread_collect_all_imports_into, freeze_component,
    freeze_component_with_class_cache, merge_imports_into as pyread_merge_imports_into,
    should_memoize as memoize_should_memoize, ClassMetadataCache, ConstructionSchema,
    MemoRefs, PyRefs,
};

/// One per Python `reflex.compiler.session.CompilerSession`. Holds the
/// content-hash-keyed compile cache (D5) so hot-reload is incremental.
///
/// `unsendable` because the session owns ``Rc<RefCell<...>>`` caches —
/// safe under the GIL (single-threaded access) but not `Send`. PyO3
/// blocks sharing across Python threads at runtime.
#[pyclass(unsendable)]
pub struct CompilerSession {
    db: CompilerDb,
    /// Long-lived per-Component-class metadata cache. Lives across
    /// `compile_page_from_component_arena` calls so warm sessions skip
    /// per-class introspection (planx.md options B + C). Wrapped in
    /// `Rc<RefCell>` for interior mutability + sharing with the
    /// per-call `PyRefs`.
    class_metadata: std::rc::Rc<std::cell::RefCell<ClassMetadataCache>>,
    /// PyO3 boundary-crossing counter incremented by the freeze pass.
    /// Exposed via `freeze_pyo3_call_count()` for the perf-regression
    /// tests; sees ~15-20 crossings per Component pre-A, ≤4 post-A.
    freeze_crossings: std::rc::Rc<std::cell::Cell<u64>>,
    /// Count of `(class, method)` pairs the skip-list cache has
    /// elided. Exposed for the C test.
    freeze_trivial_skips: std::rc::Rc<std::cell::Cell<u64>>,
    /// B: direct-from-Rust `get_props` / `_rename_props` call counts.
    /// Distinct from Python-internal calls (e.g. `_get_imports` →
    /// `_get_vars` → `get_props`) which our class cache can't
    /// suppress.
    direct_get_props_calls: std::rc::Rc<std::cell::Cell<u64>>,
    direct_rename_props_reads: std::rc::Rc<std::cell::Cell<u64>>,
    /// Prototype scaffolding for the arena-construction benchmark
    /// (`bench_push_node`) — NOT part of the compile pipeline. Holds
    /// the nodes pushed by the benchmark and the per-class schemas
    /// that simulate the construction-time classification table.
    bench_arena: std::cell::RefCell<Vec<BenchNode>>,
    bench_schemas: std::cell::RefCell<std::collections::HashMap<String, BenchSchema>>,
}

/// Benchmark-only per-class schema: which prop names are event
/// triggers. The real design derives this once per class from
/// `get_fields()` + `get_event_triggers()`; the benchmark seeds a
/// representative trigger set on first touch of each class.
struct BenchSchema {
    events: std::collections::HashSet<String>,
}

/// Benchmark-only converted prop value — the owned Rust data a real
/// `push_node` would store per prop.
enum BenchValue {
    Str(Symbol),
    Int(i64),
    Float(f64),
    Bool(bool),
    /// JS literal rendered from a list/dict prop (the work
    /// `LiteralVar.create` does today for plain containers).
    Json(String),
    /// Native Var prop — JS expression read directly off the struct.
    Var(Symbol),
    /// Event trigger value — kept as a Python handle for the probe
    /// phase (chain assembly happens at emit, already in Rust).
    Event(Py<PyAny>),
    None_,
}

#[allow(dead_code)] // tag/children stored to size the node realistically; only props read back
struct BenchNode {
    tag: Symbol,
    props: Vec<(Symbol, BenchValue)>,
    children: Vec<u32>,
}

/// Render a plain Python container as a JS literal string —
/// benchmark stand-in for the literal conversion `LiteralVar.create`
/// performs on list/dict props today.
fn bench_write_js_literal(v: &Bound<'_, PyAny>, out: &mut String) -> PyResult<()> {
    use std::fmt::Write;
    if v.is_none() {
        out.push_str("null");
    } else if let Ok(b) = v.downcast::<PyBool>() {
        out.push_str(if b.is_true() { "true" } else { "false" });
    } else if let Ok(s) = v.downcast::<PyString>() {
        out.push('"');
        for c in s.to_str()?.chars() {
            match c {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                _ => out.push(c),
            }
        }
        out.push('"');
    } else if let Ok(rv) = v.downcast::<RustVar>() {
        out.push_str(rv.get().js_expr_str());
    } else if let Ok(list) = v.downcast::<PyList>() {
        out.push('[');
        for (i, item) in list.iter().enumerate() {
            if i > 0 {
                out.push_str(", ");
            }
            bench_write_js_literal(&item, out)?;
        }
        out.push(']');
    } else if let Ok(d) = v.downcast::<PyDict>() {
        out.push_str("({ ");
        let mut first = true;
        for (k, val) in d.iter() {
            if !first {
                out.push_str(", ");
            }
            first = false;
            let _ = write!(out, "[{:?}] : ", k.str()?.to_string_lossy());
            bench_write_js_literal(&val, out)?;
        }
        out.push_str(" })");
    } else if let Ok(i) = v.extract::<i64>() {
        let _ = write!(out, "{i}");
    } else if let Ok(f) = v.extract::<f64>() {
        let _ = write!(out, "{f}");
    } else {
        out.push_str(&v.str()?.to_string_lossy());
    }
    Ok(())
}

impl CompilerSession {
    #[allow(clippy::too_many_arguments)]
    fn compile_page_from_component_arena_impl<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
        route_ident: &str,
        route: &str,
        title: Option<&str>,
        meta_tags: Option<&Bound<'py, PyList>>,
        custom_code: Option<Vec<String>>,
        hooks_body: Option<&str>,
        app_style: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<(
        String,
        Vec<(String, String)>,
        Bound<'py, PyDict>,
        Bound<'py, PyDict>,
    )> {
        let meta_pairs: Vec<(String, String)> = match meta_tags {
            Some(list) => {
                let mut out = Vec::with_capacity(list.len());
                for item in list.iter() {
                    let tup: Bound<PyTuple> = item.downcast_into()?;
                    if tup.len() != 2 {
                        return Err(pyo3::exceptions::PyValueError::new_err(
                            "meta_tags entries must be (name, content) tuples",
                        ));
                    }
                    let n: String = tup.get_item(0)?.extract()?;
                    let c: String = tup.get_item(1)?.extract()?;
                    out.push((n, c));
                }
                out
            }
            None => Vec::new(),
        };

        let custom_code_owned: Vec<String> = custom_code.unwrap_or_default();
        let hooks_owned = hooks_body.unwrap_or("").to_string();

        // PyO3-bound phase: freeze the component tree AND harvest the
        // per-page imports dict in the same walk. The accumulator
        // dict is stashed on `PyRefs::bun_imports` before freeze
        // runs; `accumulate_bun_imports` merges each Component's
        // `_get_imports()` into it inline, deduped by `id(component)`.
        // No separate `collect_all_imports` tree walk — eliminates
        // the second `_get_imports * N` PyO3 boundary cost (planx.md
        // PR7 follow-through).
        // PR-Freeze-Speedup B/C: clone session-scoped caches into
        // PyRefs so freeze can read+write per-class metadata that
        // survives across calls. Counters reset per arena entry so
        // tests see a clean number for this compile.
        self.freeze_crossings.set(0);
        let refs = PyRefs::new(py)?.with_session_caches(
            std::rc::Rc::clone(&self.class_metadata),
            std::rc::Rc::clone(&self.freeze_crossings),
            std::rc::Rc::clone(&self.freeze_trivial_skips),
            std::rc::Rc::clone(&self.direct_get_props_calls),
            std::rc::Rc::clone(&self.direct_rename_props_reads),
        );
        let imports_dict = PyDict::new_bound(py);
        *refs.bun_imports.borrow_mut() = Some(imports_dict.clone().unbind());
        // App-wrap accumulator: the freeze walk harvests each visited
        // class's `_get_app_wrap_components` output here, replacing the
        // Python `_get_all_app_wrap_components` tree walk per page.
        let app_wraps_dict = PyDict::new_bound(py);
        *refs.app_wraps.borrow_mut() = Some(app_wraps_dict.clone().unbind());
        // M2 deferred style fold: hand the `App.style` dict to the freeze
        // so it can apply the per-node fold under the fold-root mark.
        *refs.style_fold_style.borrow_mut() = app_style.map(|s| s.clone().unbind());
        let snapshot = freeze_component_with_class_cache(py, component, &refs)?;
        *refs.bun_imports.borrow_mut() = None;
        *refs.app_wraps.borrow_mut() = None;
        *refs.style_fold_style.borrow_mut() = None;

        let (page_js, memo_bodies) = emit_snapshot_to_js(
            py,
            snapshot,
            route_ident,
            route,
            title,
            meta_pairs,
            custom_code_owned,
            hooks_owned,
        );
        Ok((page_js, memo_bodies, imports_dict, app_wraps_dict))
    }

    /// PROTOTYPE — arena-construction benchmark, not a compiler entry
    /// point. One PyO3 call per component: classify `props` against
    /// the (cached) per-class schema, convert each value to owned Rust
    /// data, push a node, return its index. Measures the per-node cost
    /// the proposed construct-into-arena design would pay in place of
    /// Python `Component.__init__`.
    fn bench_push_node_impl(
        &self,
        tag: &str,
        props: &Bound<'_, PyDict>,
        children: Option<Vec<u32>>,
    ) -> PyResult<u32> {
        let mut schemas = self.bench_schemas.borrow_mut();
        let schema = schemas.entry(tag.to_owned()).or_insert_with(|| BenchSchema {
            events: [
                "on_click", "on_change", "on_blur", "on_focus", "on_submit", "on_mount",
                "on_unmount", "on_double_click", "on_key_down", "on_drop",
            ]
            .iter()
            .map(|s| (*s).to_owned())
            .collect(),
        });
        let mut out: Vec<(Symbol, BenchValue)> = Vec::with_capacity(props.len());
        for (k, v) in props.iter() {
            let key = k.downcast::<PyString>()?.to_str()?;
            let key_sym = intern(key);
            let value = if schema.events.contains(key) {
                BenchValue::Event(v.clone().unbind())
            } else if let Ok(rv) = v.downcast::<RustVar>() {
                BenchValue::Var(intern(rv.get().js_expr_str()))
            } else if let Ok(s) = v.downcast::<PyString>() {
                BenchValue::Str(intern(s.to_str()?))
            } else if v.is_none() {
                BenchValue::None_
            } else if let Ok(b) = v.downcast::<PyBool>() {
                BenchValue::Bool(b.is_true())
            } else if let Ok(f) = v.downcast::<PyFloat>() {
                BenchValue::Float(f.value())
            } else if let Ok(i) = v.extract::<i64>() {
                BenchValue::Int(i)
            } else {
                let mut s = String::with_capacity(32);
                bench_write_js_literal(&v, &mut s)?;
                BenchValue::Json(s)
            };
            out.push((key_sym, value));
        }
        let mut arena = self.bench_arena.borrow_mut();
        arena.push(BenchNode {
            tag: intern(tag),
            props: out,
            children: children.unwrap_or_default(),
        });
        Ok((arena.len() - 1) as u32)
    }

    /// PROTOTYPE — materialize one prop of a benched node back to
    /// Python (the proxy `__getattr__` read path the design needs for
    /// override classes). Returns the stored value's Python form.
    fn bench_read_prop_impl(&self, py: Python<'_>, idx: u32, name: &str) -> PyResult<PyObject> {
        let arena = self.bench_arena.borrow();
        let node = arena
            .get(idx as usize)
            .ok_or_else(|| pyo3::exceptions::PyIndexError::new_err("no such node"))?;
        let name_sym = intern(name);
        for (k, v) in &node.props {
            if *k == name_sym {
                return Ok(match v {
                    BenchValue::Str(s) => resolve_unchecked(*s).into_py(py),
                    BenchValue::Int(i) => i.into_py(py),
                    BenchValue::Float(f) => f.into_py(py),
                    BenchValue::Bool(b) => b.into_py(py),
                    BenchValue::Json(s) => s.clone().into_py(py),
                    BenchValue::Var(s) => resolve_unchecked(*s).into_py(py),
                    BenchValue::Event(o) => o.clone_ref(py),
                    BenchValue::None_ => py.None(),
                });
            }
        }
        Ok(py.None())
    }
}

/// Memoize + emit a frozen `Snapshot` into `(page_js, memo_bodies)`. The
/// GIL-released tail shared by the freeze entrypoint and the wire-bundle
/// entrypoint, so the emitted JSX is byte-identical regardless of how the
/// `Snapshot` was sourced (live freeze vs. record/wire rebuild).
#[allow(clippy::too_many_arguments)]
fn emit_snapshot_to_js(
    py: Python<'_>,
    snapshot: reflex_ir::Snapshot,
    route_ident: &str,
    route: &str,
    title: Option<&str>,
    meta_pairs: Vec<(String, String)>,
    custom_code: Vec<String>,
    hooks_body: String,
) -> (String, Vec<(String, String)>) {
    let route_ident_owned = route_ident.to_string();
    let route_owned = route.to_string();
    let title_owned = title.map(|s| s.to_owned());
    py.allow_threads(move || {
        let mut snap = snapshot;
        memoize_arena_pass(&mut snap);

        // Emit the page module.
        let mut page_buf = CodeBuffer::with_capacity(4096);
        let custom_code_refs: Vec<&str> = custom_code.iter().map(String::as_str).collect();
        emit_page_module_from_snapshot(
            &mut page_buf,
            &snap,
            &route_ident_owned,
            &route_owned,
            title_owned.as_deref(),
            &meta_pairs,
            &custom_code_refs,
            &hooks_body,
        );
        let page_js = String::from_utf8(page_buf.into_bytes()).unwrap_or_default();

        // Emit each unique memo body.
        let mut bodies: Vec<(String, String)> = Vec::with_capacity(snap.memo_bodies.len());
        let body_specs: Vec<(reflex_intern::Symbol, reflex_ir::NodeIdx)> =
            snap.memo_bodies.iter().map(|b| (b.name, b.root)).collect();
        for (name_sym, root_idx) in body_specs {
            let mut body_buf = CodeBuffer::with_capacity(2048);
            let name_str = reflex_intern::resolve_unchecked(name_sym).to_owned();
            emit_memo_module_from_snapshot(
                &mut body_buf,
                &snap,
                root_idx,
                &name_str,
                "({ children })",
                "",
            );
            let body_js = String::from_utf8(body_buf.into_bytes()).unwrap_or_default();
            bodies.push((name_str, body_js));
        }
        (page_js, bodies)
    })
}

#[pymethods]
impl CompilerSession {
    #[new]
    fn new() -> Self {
        Self {
            db: CompilerDb::new(),
            class_metadata: std::rc::Rc::new(std::cell::RefCell::new(
                ClassMetadataCache::with_capacity(32),
            )),
            freeze_crossings: std::rc::Rc::new(std::cell::Cell::new(0)),
            freeze_trivial_skips: std::rc::Rc::new(std::cell::Cell::new(0)),
            direct_get_props_calls: std::rc::Rc::new(std::cell::Cell::new(0)),
            direct_rename_props_reads: std::rc::Rc::new(std::cell::Cell::new(0)),
            bench_arena: std::cell::RefCell::new(Vec::new()),
            bench_schemas: std::cell::RefCell::new(std::collections::HashMap::new()),
        }
    }

    /// B: direct-from-Rust `get_props` invocations this session. Lets
    /// tests distinguish Rust-controlled calls from Python-internal
    /// ones (e.g. `_get_imports` → `_get_vars` → `get_props`) that
    /// our class cache cannot suppress.
    fn direct_get_props_calls(&self) -> u64 {
        self.direct_get_props_calls.get()
    }

    fn reset_direct_get_props_calls(&self) {
        self.direct_get_props_calls.set(0);
    }

    /// B: direct-from-Rust `_rename_props` reads this session.
    fn direct_rename_props_reads(&self) -> u64 {
        self.direct_rename_props_reads.get()
    }

    fn reset_direct_rename_props_reads(&self) {
        self.direct_rename_props_reads.set(0);
    }

    /// Diagnostic: count of cached classes currently in the
    /// per-session metadata cache. Used by tests to verify B has
    /// landed (presence of attr also serves as the contract pin).
    fn class_metadata_cache_size(&self) -> usize {
        self.class_metadata.borrow().len()
    }

    /// M1 (arena construction): register the construction-time kwarg
    /// classification schema for a Component class. The inputs come
    /// from `Component._construction_schema()` on the Python side; the
    /// table is stored on the per-class metadata cache. Inert —
    /// nothing consumes it until M3's `push_node`.
    fn register_class_schema(
        &self,
        cls: &Bound<'_, PyAny>,
        props: Vec<(String, bool)>,
        triggers: Vec<String>,
        base_fields: Vec<String>,
        rename_props: Vec<(String, String)>,
    ) {
        let key = cls.as_ptr() as usize;
        self.class_metadata
            .borrow_mut()
            .entry(key)
            .or_default()
            .construction_schema = Some(ConstructionSchema::new(
            props,
            triggers,
            base_fields,
            rename_props,
        ));
    }

    /// M1: whether a construction schema is registered for `cls`.
    fn class_schema_registered(&self, cls: &Bound<'_, PyAny>) -> bool {
        let key = cls.as_ptr() as usize;
        self.class_metadata
            .borrow()
            .get(&key)
            .is_some_and(|meta| meta.construction_schema.is_some())
    }

    /// M1 differential-test hook: classify one kwarg name against the
    /// registered schema for `cls`. Returns the category string
    /// matching `ConstructionSchema.classify` on the Python side, or
    /// `None` when no schema is registered for the class.
    fn class_schema_classify(&self, cls: &Bound<'_, PyAny>, name: &str) -> Option<&'static str> {
        let key = cls.as_ptr() as usize;
        self.class_metadata
            .borrow()
            .get(&key)
            .and_then(|meta| meta.construction_schema.as_ref())
            .map(|schema| schema.classify(name).as_str())
    }

    /// M1 round-trip hook: the registered rename map for `cls`, or
    /// `None` when no schema is registered.
    fn class_schema_rename_props(
        &self,
        cls: &Bound<'_, PyAny>,
    ) -> Option<Vec<(String, String)>> {
        let key = cls.as_ptr() as usize;
        self.class_metadata
            .borrow()
            .get(&key)
            .and_then(|meta| meta.construction_schema.as_ref())
            .map(|schema| schema.rename_props.clone())
    }

    /// PyO3 boundary crossings during freeze since the last reset.
    /// Used by the A perf-regression test.
    fn freeze_pyo3_call_count(&self) -> u64 {
        self.freeze_crossings.get()
    }

    fn reset_freeze_pyo3_call_count(&self) {
        self.freeze_crossings.set(0);
    }

    /// Count of `(class, method)` pairs the skip-list cache has
    /// elided in this session. C contract pin.
    fn freeze_trivial_skip_count(&self) -> u64 {
        self.freeze_trivial_skips.get()
    }

    /// Cap the page cache. Pass `None` for unbounded.
    fn set_cache_capacity(&self, cap: Option<usize>) {
        self.db.set_cache_capacity(cap);
    }

    /// PR0: write `content` to `out_path` only when the existing file's
    /// bytes differ. Returns `True` when the file was actually written,
    /// `False` when the existing contents already matched.
    ///
    /// Use this in place of `pathlib.Path.write_text` for any compile
    /// output that may be regenerated unchanged on a hot reload. Vite's
    /// dev server watches mtime; an unconditional write triggers an
    /// HMR cascade even when the bytes are identical.
    fn write_if_changed(&self, out_path: &str, content: &str) -> PyResult<bool> {
        let bytes = content.as_bytes();
        if file_matches(out_path, bytes) {
            return Ok(false);
        }
        std::fs::write(out_path, bytes)
            .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("{out_path}: {e}")))?;
        Ok(true)
    }

    /// Drop all cached page renders. Equivalent to creating a new session.
    fn clear_cache(&self) {
        self.db.clear();
    }

    /// Number of cached page renders. Useful for tests + diagnostics.
    fn cache_len(&self) -> usize {
        self.db.cache_len()
    }

    /// Emit the memo index module to `out_path`.
    ///
    /// Streams the rendered bytes straight to disk via a
    /// `BufWriter<File>` — no intermediate `String` allocation. Mirrors
    /// `memo_index_template` in
    /// `packages/reflex-base/src/reflex_base/compiler/templates.py`.
    ///
    /// Args:
    ///     reexports: list of `(export_name, relative_module_specifier)`
    ///         tuples.
    ///     out_path: absolute filesystem path the index gets written to.
    ///         Parent directory must already exist.
    fn compile_memo_index(&self, reexports: Vec<(String, String)>, out_path: &str) -> PyResult<()> {
        let pairs: Vec<(&str, &str)> = reexports
            .iter()
            .map(|(n, s)| (n.as_str(), s.as_str()))
            .collect();
        write_to_file(out_path, |w| emit_memo_index(&pairs, w))
    }

    /// Emit `.web/styles/styles.css`.
    ///
    /// Ports `styles_template` — wraps every stylesheet in an
    /// `@import url('…');` line under a single
    /// `@layer __reflex_base;` header.
    fn compile_styles_root(&self, stylesheets: Vec<String>, out_path: &str) -> PyResult<()> {
        let refs: Vec<&str> = stylesheets.iter().map(String::as_str).collect();
        write_to_file(out_path, |w| emit_styles_root(&refs, w))
    }

    /// Emit `.web/utils/theme.js` directly from a theme Component.
    ///
    /// Ports `theme_template` — a single `export default <theme_js>`
    /// line. The theme Component crosses the PyO3 boundary so
    /// `rust_pipeline.py` never has to import `LiteralVar` or pre-render
    /// the JS string itself; the rendering hop still happens here via
    /// `LiteralVar.create(theme_component)` for byte parity with the
    /// retired string-input entry.
    fn compile_theme_from_component_arena<'py>(
        &self,
        py: Python<'py>,
        theme_component: &Bound<'py, PyAny>,
        out_path: &str,
    ) -> PyResult<()> {
        let literal_var = py
            .import_bound("reflex_base.vars.base")?
            .getattr("LiteralVar")?;
        let wrapped = literal_var.call_method1("create", (theme_component,))?;
        let theme_js: String = wrapped.str()?.extract()?;
        write_to_file(out_path, |w| emit_theme_module(&theme_js, w))
    }

    /// Emit `.web/backend/stateful_pages.json`.
    ///
    /// Mirrors `App._write_stateful_pages_marker`. Python decides which
    /// routes are stateful (it requires a state walk we haven't ported);
    /// Rust just serializes the list as JSON and writes the file.
    fn compile_stateful_pages_marker(&self, routes: Vec<String>, out_path: &str) -> PyResult<()> {
        let refs: Vec<&str> = routes.iter().map(String::as_str).collect();
        write_to_file(out_path, |w| emit_stateful_pages_json(&refs, w))
    }

    /// Emit `.web/utils/context.js`.
    ///
    /// Ports `context_template` from
    /// `packages/reflex-base/src/reflex_base/compiler/templates.py`.
    ///
    /// Args:
    ///     is_dev_mode: emitted as `export const isDevMode = …`.
    ///     default_color_mode_js: the JS expression assigned to
    ///         `defaultColorMode` (a quoted string or a lookup expr).
    ///     state_name: full dotted name of the state root, or `None`
    ///         for the no-state fallback.
    ///     state_keys: full dotted names of every state context.
    ///     initial_state_json: pre-serialized initial-state dict.
    ///     client_storage_json: pre-serialized client-storage config.
    /// Emit `.web/app/root.jsx` from an app-root Component.
    ///
    /// Replaces the previous string-input `compile_app_root_module` shim
    /// that required the Python caller to first run
    /// `_RenderUtils.render(component.render())`, `_render_hooks`,
    /// `component._get_all_custom_code()`,
    /// `component._get_all_dynamic_imports()`, and the import-format
    /// chain. All of those now live on the Rust side of the freeze +
    /// harvest + emit pipeline:
    ///
    /// 1. Freeze the Component tree once (the bun_imports accumulator
    ///    on `PyRefs` captures each node's `_get_imports()` inline).
    /// 2. With the GIL released: emit the JSX via
    ///    `emit_jsx_compact_from_snapshot` (matches the legacy
    ///    `_RenderUtils.render` no-space format byte-for-byte),
    ///    harvest `custom_code` / `dynamic_imports` from the snapshot,
    ///    render the hooks block via `render_hooks`.
    /// 3. With the GIL: format the imports lines via the Python
    ///    helpers `_apply_common_imports` + `compile_imports` +
    ///    `_RenderUtils.get_import` (these are NOT one of the four
    ///    aggregating `_get_all_*` methods).
    /// 4. Splice everything into `emit_app_root_module` and write.
    ///
    /// Returns the bun-install imports dict (post-alias-prefix) so the
    /// caller can merge it into the global install set.
    fn compile_app_root_arena<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
        import_window_libraries: &str,
        window_imports: &str,
        out_path: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        self.freeze_crossings.set(0);
        let refs = PyRefs::new(py)?.with_session_caches(
            std::rc::Rc::clone(&self.class_metadata),
            std::rc::Rc::clone(&self.freeze_crossings),
            std::rc::Rc::clone(&self.freeze_trivial_skips),
            std::rc::Rc::clone(&self.direct_get_props_calls),
            std::rc::Rc::clone(&self.direct_rename_props_reads),
        );
        let imports_dict = PyDict::new_bound(py);
        *refs.bun_imports.borrow_mut() = Some(imports_dict.clone().unbind());
        let snapshot = freeze_component_with_class_cache(py, component, &refs)?;
        *refs.bun_imports.borrow_mut() = None;

        // GIL released: emit JSX (compact format matching legacy
        // `_RenderUtils.render`), harvest custom_code +
        // dynamic_imports as strings, render hooks block.
        let (render_str, custom_code_str, dynamic_imports_str, hooks_str) =
            py.allow_threads(|| {
                let mut buf = CodeBuffer::with_capacity(4096);
                emit_jsx_compact_from_snapshot(&mut buf, &snapshot);
                let render = String::from_utf8(buf.into_bytes()).unwrap_or_default();

                let custom_code = collect_custom_code(&snapshot)
                    .into_iter()
                    .map(|s| resolve_unchecked(s).to_owned())
                    .collect::<Vec<_>>()
                    .join("\n");

                let dyn_imports = collect_dynamic_imports(&snapshot)
                    .into_iter()
                    .map(|s| resolve_unchecked(s).to_owned())
                    .collect::<Vec<_>>()
                    .join("\n");

                let hooks = render_hooks_unfiltered(&snapshot, &[]);
                (render, custom_code, dyn_imports, hooks)
            });

        // Format imports via Python helpers — these don't touch the
        // four `_get_all_*` aggregators (the patched set) and reuse
        // the legacy `_RenderUtils.get_import` formatter so the
        // resulting lines are byte-identical to the previous Python
        // chain that fed the string-input `compile_app_root_module`.
        let imports_str = format_imports_via_python(py, &imports_dict)?;

        write_to_file(out_path, |w| {
            emit_app_root_module(
                &imports_str,
                &dynamic_imports_str,
                &custom_code_str,
                &hooks_str,
                &render_str,
                import_window_libraries,
                window_imports,
                w,
            )
        })?;
        Ok(imports_dict)
    }

    /// Compile one ``@rx.memo`` component module and write it to
    /// ``out_path`` — component in, file out, imports dict back.
    ///
    /// One arena freeze replaces the legacy per-tree Python harvest
    /// (``render()`` + the four ``_get_all_*`` aggregators); the whole
    /// module assembles in Rust mirroring the legacy
    /// ``memo_single_component_template`` byte-for-byte. The only
    /// Python callback is the one-shot import-header formatter
    /// (``_format_memo_imports``) over the harvested dict — full
    /// ``ImportVar`` fidelity (default imports, render flags) lives
    /// there, same as the app-root/document/theme emitters. No memoize
    /// pass and no trigger rewrite run here — an rx.memo module
    /// renders its event chains inline, exactly like the legacy
    /// emitter.
    fn compile_rx_memo_arena<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
        export_name: &str,
        signature: &str,
        out_path: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        self.freeze_crossings.set(0);
        let refs = PyRefs::new(py)?.with_session_caches(
            std::rc::Rc::clone(&self.class_metadata),
            std::rc::Rc::clone(&self.freeze_crossings),
            std::rc::Rc::clone(&self.freeze_trivial_skips),
            std::rc::Rc::clone(&self.direct_get_props_calls),
            std::rc::Rc::clone(&self.direct_rename_props_reads),
        );
        let imports_dict = PyDict::new_bound(py);
        *refs.bun_imports.borrow_mut() = Some(imports_dict.clone().unbind());
        let snapshot = freeze_component_with_class_cache(py, component, &refs)?;
        *refs.bun_imports.borrow_mut() = None;

        let (render_str, hooks_str, custom_code_str, dynamic_imports_str) =
            py.allow_threads(|| {
                let mut buf = CodeBuffer::with_capacity(4096);
                emit_jsx_compact_from_snapshot(&mut buf, &snapshot);
                let render = String::from_utf8(buf.into_bytes()).unwrap_or_default();

                let custom = collect_custom_code(&snapshot)
                    .into_iter()
                    .map(|s| resolve_unchecked(s).to_owned())
                    .collect::<Vec<_>>()
                    .join("\n");

                let mut dyns = collect_dynamic_imports(&snapshot)
                    .into_iter()
                    .map(|s| resolve_unchecked(s).to_owned())
                    .collect::<Vec<_>>();
                dyns.sort();
                let dyns = dyns.join("\n");

                let hooks = render_hooks_rx_memo(&snapshot);
                (render, hooks, custom, dyns)
            });

        let (imports_str, merged_imports) =
            format_memo_imports_via_python(py, &imports_dict, export_name)?;

        // Assemble the module exactly like the legacy template:
        // \n{imports}\n\n{dyn}\n\n{custom}\n\n
        // \nexport const {name} = memo(({sig}) => {\n    {hooks}\n
        //     return(\n        {jsx}\n    )\n});\n
        let mut module =
            String::with_capacity(imports_str.len() + hooks_str.len() + render_str.len() + 256);
        module.push('\n');
        module.push_str(&imports_str);
        module.push_str("\n\n");
        module.push_str(&dynamic_imports_str);
        module.push_str("\n\n");
        module.push_str(&custom_code_str);
        module.push_str("\n\n\nexport const ");
        module.push_str(export_name);
        module.push_str(" = memo((");
        module.push_str(signature);
        module.push_str(") => {\n    ");
        module.push_str(&hooks_str);
        module.push_str("\n    return(\n        ");
        module.push_str(&render_str);
        module.push_str("\n    )\n});\n");

        self.write_if_changed(out_path, &module)?;
        Ok(merged_imports)
    }

    /// Emit `.web/app/_document.js` from a pre-built document-root
    /// Component tree.
    ///
    /// The Python wrapper `CompilerSession.compile_document_root_arena`
    /// composes the `<html><head><body>` shell (user
    /// `head_components` are user Python and stay there); the assembled
    /// tree crosses the PyO3 boundary once here. Internally:
    ///
    /// 1. Freeze the Component (bun_imports accumulator captures
    ///    every node's `_get_imports()`).
    /// 2. With the GIL released: render the JSX via the compact emit
    ///    so the embedded payload matches the legacy
    ///    `_RenderUtils.render(document_root.render())` shape.
    /// 3. With the GIL: format imports via the Python helpers
    ///    (`_apply_common_imports` + `compile_imports` +
    ///    `_RenderUtils.get_import`) — the same byte format the prior
    ///    string-input shim produced.
    /// 4. Splice into `emit_document_root_module` and write.
    fn compile_document_root_arena<'py>(
        &self,
        py: Python<'py>,
        document_root_component: &Bound<'py, PyAny>,
        out_path: &str,
    ) -> PyResult<()> {
        let refs = PyRefs::new(py)?;
        let imports_dict = PyDict::new_bound(py);
        *refs.bun_imports.borrow_mut() = Some(imports_dict.clone().unbind());
        let snapshot = freeze_component(py, document_root_component, &refs)?;
        *refs.bun_imports.borrow_mut() = None;

        let render_str = py.allow_threads(|| {
            let mut buf = CodeBuffer::with_capacity(2048);
            emit_jsx_compact_from_snapshot(&mut buf, &snapshot);
            String::from_utf8(buf.into_bytes()).unwrap_or_default()
        });

        let imports_str = format_imports_via_python(py, &imports_dict)?;

        write_to_file(out_path, |w| {
            emit_document_root_module(&imports_str, &render_str, w)
        })
    }

    #[pyo3(signature = (is_dev_mode, default_color_mode_js, state_name, state_keys, initial_state_json, client_storage_json, out_path))]
    fn compile_context_module(
        &self,
        is_dev_mode: bool,
        default_color_mode_js: &str,
        state_name: Option<&str>,
        state_keys: Vec<String>,
        initial_state_json: &str,
        client_storage_json: &str,
        out_path: &str,
    ) -> PyResult<()> {
        let keys: Vec<&str> = state_keys.iter().map(String::as_str).collect();
        write_to_file(out_path, |w| {
            emit_context_module(
                is_dev_mode,
                default_color_mode_js,
                state_name,
                &keys,
                initial_state_json,
                client_storage_json,
                w,
            )
        })
    }

    /// PR3 parity entry point. Freezes ``component`` into a one-node
    /// arena snapshot and applies ``should_memoize_arena`` to the
    /// root. Used by the parity oracle test
    /// (``tests/units/compiler/test_arena_parity.py``) to compare the
    /// Rust predicate against Python ``_should_memoize`` on real
    /// Component fixtures — without spinning up a full page compile.
    fn should_memoize_arena_for_component<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<bool> {
        let refs = PyRefs::new(py)?;
        let snapshot = freeze_component(py, component, &refs)?;
        if snapshot.nodes.is_empty() {
            return Ok(false);
        }
        Ok(reflex_codegen::should_memoize_arena(
            &snapshot,
            snapshot.root,
        ))
    }

    /// PR7 verification helper. Returns a stats dict from a freshly
    /// frozen ``component``: ``node_count``, ``var_data_len``,
    /// ``vars_used_total``, ``unique_var_ids``. The dedup tests rely
    /// on ``var_data_len == unique_var_ids`` and
    /// ``vars_used_total >= var_data_len``.
    fn snapshot_stats<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let refs = PyRefs::new(py)?;
        let snapshot = freeze_component(py, component, &refs)?;
        let node_count = snapshot.nodes.len();
        let var_data_len = snapshot.var_data.len();
        let vars_used_total: usize = snapshot.nodes.iter().map(|n| n.vars_used.len()).sum();
        // `unique_var_ids` counts the distinct snapshot indices stored
        // in any node's `vars_used` SmallVec. Equals `var_data_len`
        // once dedup lands; without dedup it would equal
        // `vars_used_total`.
        let mut seen: std::collections::HashSet<u32> = std::collections::HashSet::new();
        for n in &snapshot.nodes {
            for r in &n.vars_used {
                seen.insert(r.0);
            }
        }
        let unique_var_ids = seen.len();
        let d = PyDict::new_bound(py);
        d.set_item("node_count", node_count)?;
        d.set_item("var_data_len", var_data_len)?;
        d.set_item("vars_used_total", vars_used_total)?;
        d.set_item("unique_var_ids", unique_var_ids)?;
        Ok(d)
    }

    /// Run the memoize-decision walk on a Component PyObject.
    ///
    /// Ports `reflex.compiler.plugins.memoize._should_memoize` to Rust
    /// (plan §0a phase 2 / §0b lever (b2)). Behavior-identical with the
    /// legacy predicate: for any Component the legacy plugin would
    /// memoize, this returns True; for any it would skip, False.
    ///
    /// Used by:
    ///
    /// * Parity tests (`tests/units/compiler/test_memoize_plugin.py`).
    /// * Phase 3 (wrapper construction in Rust) — once the decision is
    ///   produced here, the same walk can drive `Component::Memoize`
    ///   wrapping during pyread.
    fn should_memoize<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<bool> {
        let pyrefs = PyRefs::new(py)?;
        let refs = MemoRefs::from_pyrefs(py, &pyrefs)?;
        Ok(memoize_should_memoize(py, component, &refs)?)
    }

    /// Mirror `Component._get_all_imports()` with the merge happening in
    /// Rust. Walks `component`'s children + `_get_components_in_props()`,
    /// calls each node's cached `_get_imports()`, and merges into a
    /// `HashMap` rather than the Python `merge_parsed_imports` recursion.
    ///
    /// Returns the same shape `_get_all_imports` returns:
    /// `dict[str, list[ImportVar]]` with no library-prefix transform —
    /// callers wrap in `merge_imports(...)` for the `$/utils/...`
    /// rewrite.
    fn collect_all_imports<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        pyread_collect_all_imports(py, component)
    }

    /// In-place variant of [`collect_all_imports`]: walks `component`'s
    /// tree and merges every entry into `target` with the
    /// `merge_imports` library-prefix transform (`$/utils/...`)
    /// applied. The caller-owned `target` dict is mutated.
    ///
    /// Replaces the
    /// `merge_imports(target, component._get_all_imports())` pattern in
    /// `rust_pipeline.compile_pages` — accumulating across pages
    /// into one dict cuts the O(N²) outer-loop iteration the Python
    /// pattern incurs.
    fn collect_all_imports_into<'py>(
        &self,
        py: Python<'py>,
        target: &Bound<'py, PyDict>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<()> {
        pyread_collect_all_imports_into(py, target, component)
    }

    /// Apply the `merge_imports` library-prefix transform to every
    /// entry of `source` and append into `target` in place. Use this
    /// for dicts that aren't paired with a Component tree walk (custom
    /// component imports, hand-built import dicts), where the tree-
    /// walking [`collect_all_imports_into`] doesn't apply.
    fn merge_imports_into<'py>(
        &self,
        py: Python<'py>,
        target: &Bound<'py, PyDict>,
        source: &Bound<'py, PyDict>,
    ) -> PyResult<()> {
        pyread_merge_imports_into(py, target, source)
    }

    /// Snapshot the Rust-side per-phase timings from the most recent
    /// `compile_page_from_component` (or `read_page` directly). Returns
    /// a `dict[str, int]` keyed by phase name with nanosecond totals.
    ///
    /// Counters reset at the start of every `read_page`. Phase names
    /// mirror the call sites in `pyo3_reader.rs`:
    ///
    /// * `class_name_ns` — `type(c).__name__` dispatch
    /// * `resolve_tag_ns` — alias/tag/library reads in `resolve_tag_symbol`
    /// * `import_alias_ns` — same attrs re-read in `import_alias_for`
    /// * `read_props_ns`, `read_children_ns`, `read_event_handlers_ns`
    /// * `read_var_data_ns` — Var._get_all_var_data + decode
    /// * `harvest_register_ns` — RefCell mutations
    /// * `emit_ns` — pure-Rust IR → JSX string build
    /// * `read_page_total_ns` — end-to-end `read_page`
    fn last_phase_timings_ns<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let t = reflex_pyread::timing::snapshot();
        let d = PyDict::new_bound(py);
        d.set_item("read_page_total_ns", t.read_page_total_ns)?;
        d.set_item("emit_ns", t.emit_ns)?;
        d.set_item("class_name_ns", t.class_name_ns)?;
        d.set_item("resolve_tag_ns", t.resolve_tag_ns)?;
        d.set_item("import_alias_ns", t.import_alias_ns)?;
        d.set_item("read_var_data_ns", t.read_var_data_ns)?;
        d.set_item("harvest_register_ns", t.harvest_register_ns)?;
        d.set_item("get_props_call_ns", t.get_props_call_ns)?;
        d.set_item("prop_value_getattr_ns", t.prop_value_getattr_ns)?;
        d.set_item("children_attr_ns", t.children_attr_ns)?;
        d.set_item("event_triggers_attr_ns", t.event_triggers_attr_ns)?;
        d.set_item("isinstance_var_ns", t.isinstance_var_ns)?;
        d.set_item("value_literal_dispatch_ns", t.value_literal_dispatch_ns)?;
        d.set_item("var_js_expr_attr_ns", t.var_js_expr_attr_ns)?;
        // Counts.
        d.set_item("node_count", t.node_count)?;
        d.set_item("element_count", t.element_count)?;
        d.set_item("var_count", t.var_count)?;
        d.set_item("prop_count", t.prop_count)?;
        d.set_item("event_handler_count", t.event_handler_count)?;
        // Arena freeze (production path) leaf spans.
        d.set_item("freeze_total_ns", t.freeze_total_ns)?;
        d.set_item("freeze_structural_ns", t.freeze_structural_ns)?;
        d.set_item("freeze_imports_ns", t.freeze_imports_ns)?;
        d.set_item("freeze_props_ns", t.freeze_props_ns)?;
        d.set_item("freeze_style_ns", t.freeze_style_ns)?;
        d.set_item("freeze_events_ns", t.freeze_events_ns)?;
        d.set_item("freeze_hooks_ns", t.freeze_hooks_ns)?;
        d.set_item("freeze_optional_ns", t.freeze_optional_ns)?;
        d.set_item("freeze_imports_slow_ns", t.freeze_imports_slow_ns)?;
        d.set_item("imports_fast_count", t.imports_fast_count)?;
        d.set_item("imports_slow_count", t.imports_slow_count)?;
        Ok(d)
    }

    /// PR4: full-arena page compile. Freezes `component` into a
    /// `Snapshot`, runs `memoize_arena_pass` to insert wrapper
    /// redirects + register memo bodies, then emits the page JSX and
    /// each memo body module — all in Rust, GIL released after the
    /// PyO3 freeze walk.
    ///
    /// Returns `(page_js, memo_bodies, imports)` where:
    ///
    /// * `page_js` is the rendered `.web/app/routes/<route>.jsx`
    ///   contents (full module: imports + `export default function
    ///   Component()` shell + memoize wrappers at call sites).
    /// * `memo_bodies` is a list of `(name, jsx)` for each unique
    ///   memoize body. The Python caller writes each to
    ///   `.web/utils/components/<name>.jsx`.
    /// * `imports` is the page-level harvested import dict (matches
    ///   the shape `Component._get_all_imports()` produces) so the
    ///   `bun install` step still sees every npm package.
    ///
    /// Replaces, in one PyO3 round-trip, the legacy pipeline of:
    ///
    /// 1. Python `walk_and_memoize(component)` (recursive tree walk +
    ///    `Component.create` per wrapper + `_compute_memo_tag` hash chain)
    /// 2. Python `page_to_ir(component)` (msgpack pack)
    /// 3. Rust `compile_page_from_bytes` (msgpack parse + emit)
    /// 4. Python `emit_memo_modules` (per-body re-walk + render)
    #[pyo3(signature = (component, route_ident, route, title=None, meta_tags=None, custom_code=None, hooks_body=None, app_style=None))]
    #[allow(clippy::too_many_arguments)]
    fn compile_page_from_component_arena<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
        route_ident: &str,
        route: &str,
        title: Option<&str>,
        meta_tags: Option<&Bound<'py, PyList>>,
        custom_code: Option<Vec<String>>,
        hooks_body: Option<&str>,
        app_style: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<(
        String,
        Vec<(String, String)>,
        Bound<'py, PyDict>,
        Bound<'py, PyDict>,
    )> {
        let (page_js, memo_bodies, imports_dict, app_wraps_dict) = self
            .compile_page_from_component_arena_impl(
                py,
                component,
                route_ident,
                route,
                title,
                meta_tags,
                custom_code,
                hooks_body,
                app_style,
            )?;
        Ok((page_js, memo_bodies, imports_dict, app_wraps_dict))
    }

    /// PROTOTYPE — arena-construction benchmark entry. See
    /// `bench_push_node_impl` for what it measures.
    #[pyo3(signature = (tag, props, children=None))]
    fn bench_push_node(
        &self,
        tag: &str,
        props: &Bound<'_, PyDict>,
        children: Option<Vec<u32>>,
    ) -> PyResult<u32> {
        self.bench_push_node_impl(tag, props, children)
    }

    /// PROTOTYPE — companion to `bench_push_node`: node count.
    fn bench_arena_len(&self) -> usize {
        self.bench_arena.borrow().len()
    }

    /// PROTOTYPE — companion to `bench_push_node`: reset between runs.
    fn bench_arena_clear(&self) {
        self.bench_arena.borrow_mut().clear();
    }

    /// PROTOTYPE — proxy-read path: materialize one stored prop back
    /// to Python.
    fn bench_read_prop(&self, py: Python<'_>, idx: u32, name: &str) -> PyResult<PyObject> {
        self.bench_read_prop_impl(py, idx, name)
    }
}

/// Open `out_path` for buffered write and run `f` on the writer, mapping
/// any `io::Error` into a Python `OSError`.
///
/// PR0: writes go through an in-memory `Vec<u8>` first; the result is
/// only flushed to disk when its bytes differ from the existing file
/// (fstat-fast-path + memcmp). On no-op recompiles the file's mtime is
/// unchanged and downstream watchers (Vite HMR, file-change hooks)
/// don't fire.
///
/// Used by every "build content + write to disk" PyO3 method on
/// `CompilerSession` so the buffering, error mapping, and flush
/// behaviour stay consistent across the whole static-artifact surface.
fn write_to_file<F>(out_path: &str, f: F) -> PyResult<()>
where
    F: FnOnce(&mut Vec<u8>) -> std::io::Result<()>,
{
    let mut buf: Vec<u8> = Vec::with_capacity(4096);
    f(&mut buf).map_err(|e| pyo3::exceptions::PyOSError::new_err(e.to_string()))?;
    write_bytes_if_changed(out_path, &buf)
}

/// Write `content` to `out_path` only when the existing file's bytes
/// differ. PR0 helper exposed to PyO3 callers via
/// `CompilerSession::write_if_changed` so the Python pipeline can route
/// its own renders (page JSX, custom-component JSX) through the same
/// gate.
pub(crate) fn write_bytes_if_changed(out_path: &str, content: &[u8]) -> PyResult<()> {
    if file_matches(out_path, content) {
        return Ok(());
    }
    std::fs::write(out_path, content)
        .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("{out_path}: {e}")))
}

/// Format a freeze-collected `bun_imports` dict into the legacy
/// `import {...} from "..."` line block.
///
/// Drives the same chain `_compile_document_root` / `_compile_app`
/// used in the legacy compile, minus the
/// `component._get_all_imports()` call (that's covered by the
/// `PyRefs::bun_imports` accumulator filled inline during freeze).
/// The three Python helpers it touches —
/// `reflex.compiler.compiler._apply_common_imports`,
/// `reflex.compiler.utils.compile_imports`,
/// `reflex_base.compiler.templates._RenderUtils.get_import` — are NOT
/// any of the four aggregating `_get_all_*` methods that the arena
/// pipeline must avoid, so this still satisfies the no-legacy-harvest
/// contract.
fn format_imports_via_python<'py>(
    py: Python<'py>,
    bun_imports: &Bound<'py, PyDict>,
) -> PyResult<String> {
    let compiler_mod = py.import_bound("reflex.compiler.compiler")?;
    let utils_mod = py.import_bound("reflex.compiler.utils")?;
    let templates_mod = py.import_bound("reflex_base.compiler.templates")?;

    let apply_common = compiler_mod.getattr("_apply_common_imports")?;
    let compile_imports = utils_mod.getattr("compile_imports")?;
    let render_utils = templates_mod.getattr("_RenderUtils")?;
    let get_import = render_utils.getattr("get_import")?;

    apply_common.call1((bun_imports.clone(),))?;
    let modules = compile_imports.call1((bun_imports.clone(),))?;
    let modules_iter = modules.iter()?;
    let mut out_lines: Vec<String> = Vec::new();
    for module in modules_iter {
        let module = module?;
        let line: String = get_import.call1((module,))?.extract()?;
        out_lines.push(line);
    }
    Ok(out_lines.join("\n"))
}

/// Format one rx.memo module's import header via the legacy Python
/// formatter (`reflex.compiler.compiler._format_memo_imports`): strips
/// the memo's self-import, merges the memo runtime seeds + common
/// imports, and renders the lines. Returns the header and the merged
/// import dict (the bun-install contribution).
fn format_memo_imports_via_python<'py>(
    py: Python<'py>,
    bun_imports: &Bound<'py, PyDict>,
    export_name: &str,
) -> PyResult<(String, Bound<'py, PyDict>)> {
    let compiler_mod = py.import_bound("reflex.compiler.compiler")?;
    let result = compiler_mod
        .getattr("_format_memo_imports")?
        .call1((bun_imports.clone(), export_name))?;
    let header: String = result.get_item(0)?.extract()?;
    let merged = result.get_item(1)?.downcast::<PyDict>()?.clone();
    Ok((header, merged))
}

fn file_matches(path: &str, content: &[u8]) -> bool {
    let meta = match std::fs::metadata(path) {
        Ok(m) => m,
        Err(_) => return false,
    };
    if meta.len() as usize != content.len() {
        return false;
    }
    matches!(std::fs::read(path), Ok(bytes) if bytes == content)
}
