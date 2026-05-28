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
use pyo3::types::{PyDict, PyList, PyTuple};

use reflex_codegen::{
    emit_app_root_module, emit_context_module, emit_document_root_module, emit_memo_index,
    emit_memo_module_from_snapshot, emit_page_module_from_snapshot, emit_stateful_pages_json,
    emit_styles_root, emit_theme_module, memoize_arena_pass, CodeBuffer,
};
use reflex_db::CompilerDb;
use reflex_pyread::{
    collect_all_imports as pyread_collect_all_imports,
    collect_all_imports_into as pyread_collect_all_imports_into, freeze_component,
    freeze_component_with_class_cache, merge_imports_into as pyread_merge_imports_into,
    should_memoize as memoize_should_memoize, ClassMetadataCache, MemoRefs, PyRefs,
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
    /// PR F incremental compile: content-addressed page-emit cache keyed
    /// on a complete hash of the snapshot's emit inputs + the page params.
    /// On a hot-reload where a page's content is unchanged, the memoize +
    /// emit tail is skipped and the cached `(page_js, memo_bodies)` is
    /// returned. Keyed soundly (see `compute_emit_cache_key`), so a cache
    /// hit is byte-identical to a fresh emit.
    page_emit_cache: std::rc::Rc<
        std::cell::RefCell<std::collections::HashMap<u64, (String, Vec<(String, String)>)>>,
    >,
    /// Whether the page-emit cache is consulted. Off by default so the
    /// default pipeline behaviour (and the parity tests) re-emit every
    /// call; hot-reload drivers opt in via `set_emit_cache_enabled(True)`.
    emit_cache_enabled: std::rc::Rc<std::cell::Cell<bool>>,
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
            page_emit_cache: std::rc::Rc::new(std::cell::RefCell::new(
                std::collections::HashMap::new(),
            )),
            emit_cache_enabled: std::rc::Rc::new(std::cell::Cell::new(false)),
        }
    }

    /// Enable/disable the content-addressed page-emit cache (PR F). Off by
    /// default; hot-reload drivers turn it on so unchanged pages skip the
    /// memoize + emit tail.
    fn set_emit_cache_enabled(&self, enabled: bool) {
        self.emit_cache_enabled.set(enabled);
    }

    /// Render a component's event-trigger chain to JS entirely in Rust,
    /// from raw data extracted cheaply over PyO3 (no
    /// `LiteralVar.create(chain)._js_expr` — that Python render is ~109us
    /// per chain and is the gather path's dominant cost). Must be
    /// byte-identical to the Python render. STUB: returns "" until the
    /// Rust event renderer (PR D-events-rust) lands — driven by
    /// `test_event_render_rust.py`.
    fn render_event_chain_js<'py>(
        &self,
        _py: Python<'py>,
        _component: &Bound<'py, PyAny>,
        _trigger: &str,
    ) -> PyResult<String> {
        Ok(String::new())
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
        self.page_emit_cache.borrow_mut().clear();
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

    /// Emit `.web/utils/theme.js`.
    ///
    /// Ports `theme_template` — a single
    /// `export default <theme_js>` line where `theme_js` is the JS
    /// object literal Python builds via `LiteralVar.create(theme)`.
    fn compile_theme_module(&self, theme_js: &str, out_path: &str) -> PyResult<()> {
        write_to_file(out_path, |w| emit_theme_module(theme_js, w))
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
    /// Emit `.web/app/root.jsx`.
    ///
    /// Ports `app_root_template`. Python pre-renders the dynamic
    /// strings (imports, hooks, render_str, …) using
    /// `_RenderUtils.render` + friends — those depend on the legacy
    /// Python JSX renderer. Rust splices them into the static layout.
    fn compile_app_root_module(
        &self,
        imports_str: &str,
        dynamic_imports_str: &str,
        custom_code_str: &str,
        hooks_str: &str,
        render_str: &str,
        import_window_libraries: &str,
        window_imports_str: &str,
        out_path: &str,
    ) -> PyResult<()> {
        write_to_file(out_path, |w| {
            emit_app_root_module(
                imports_str,
                dynamic_imports_str,
                custom_code_str,
                hooks_str,
                render_str,
                import_window_libraries,
                window_imports_str,
                w,
            )
        })
    }

    /// Emit `.web/app/_document.js`.
    ///
    /// Ports `document_root_template`. Python pre-renders the imports
    /// list and the document JSX expression; Rust splices both into
    /// the layout function.
    fn compile_document_root_module(
        &self,
        imports_str: &str,
        document_render_str: &str,
        out_path: &str,
    ) -> PyResult<()> {
        write_to_file(out_path, |w| {
            emit_document_root_module(imports_str, document_render_str, w)
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

    /// Freeze a Component tree and return its `Snapshot` as a plain dict.
    ///
    /// The dump is the parity-oracle vehicle for the Python-freezer work
    /// (refine-local plan, PR A): comparing
    /// `dump_snapshot(build_from_wire(gather(c)))` against
    /// `dump_snapshot(component)` proves the gather path matches the Rust
    /// freeze walk byte-for-byte without re-implementing rendering in
    /// Python. The snapshot is dumped *before* `memoize_arena_pass`, so it
    /// is the pure frozen tree (no wrapper redirects / memo bodies).
    ///
    /// `id(component)` values (`node_pyids`) are intentionally omitted —
    /// see `snapshot_dump`.
    fn dump_snapshot<'py>(
        &self,
        py: Python<'py>,
        component: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let refs = PyRefs::new(py)?;
        let snapshot = freeze_component(py, component, &refs)?;
        crate::snapshot_dump::snapshot_to_pydict(py, &snapshot)
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
    /// * `needs_ref_ns` — `getattr("id")` check
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
        d.set_item("needs_ref_ns", t.needs_ref_ns)?;
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
    #[pyo3(signature = (component, route_ident, route, title=None, meta_tags=None, custom_code=None, hooks_body=None))]
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
    ) -> PyResult<(String, Vec<(String, String)>, Bound<'py, PyDict>)> {
        let meta_pairs = parse_meta_tags(meta_tags)?;

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
        let snapshot = freeze_component_with_class_cache(py, component, &refs)?;
        *refs.bun_imports.borrow_mut() = None;

        // Release the GIL for the in-arena memoize + emit. None of the
        // following calls touch Python state — they read Snapshot,
        // write to `CodeBuffer`s, and return owned `String`s.
        let (page_js, memo_bodies) = self.emit_page_and_memo_bodies(
            py,
            snapshot,
            route_ident,
            route,
            title,
            meta_pairs,
            custom_code_owned,
            hooks_owned,
        );

        Ok((page_js, memo_bodies, imports_dict))
    }

    /// Arena page compile from a pre-gathered wire bundle (refine-local
    /// plan, PR A). Identical to [`Self::compile_page_from_component_arena`]
    /// from the snapshot onward — it just sources the `Snapshot` by
    /// rebuilding it from the `bundle` dict (the inverse of
    /// `dump_snapshot`) instead of freezing a live Component tree. The
    /// emit tail is shared (`emit_page_and_memo_bodies`), so the page JSX +
    /// memo bodies are byte-identical to the freeze path for an equivalent
    /// snapshot.
    ///
    /// Unlike the freeze entrypoint this does not return a page-level
    /// imports dict: the bundle carries per-node imports inside the
    /// snapshot, but the page-level `bun install` dict is harvested
    /// separately by the caller (it is gathered alongside the bundle on
    /// the Python side, mirroring the freeze path's `bun_imports`).
    ///
    /// `compute_close` controls the `subtree_hash` / `PROPAGATES_HOOKS`
    /// close pass: pass `False` for a `dump_snapshot` bundle (those fields
    /// are already present and restored verbatim), `True` for a native
    /// gatherer bundle that omits them so Rust recomputes them.
    #[pyo3(signature = (bundle, route_ident, route, title=None, meta_tags=None, custom_code=None, hooks_body=None, compute_close=false))]
    #[allow(clippy::too_many_arguments)]
    fn compile_page_from_arena(
        &self,
        py: Python<'_>,
        bundle: &Bound<'_, PyDict>,
        route_ident: &str,
        route: &str,
        title: Option<&str>,
        meta_tags: Option<&Bound<'_, PyList>>,
        custom_code: Option<Vec<String>>,
        hooks_body: Option<&str>,
        compute_close: bool,
    ) -> PyResult<(String, Vec<(String, String)>)> {
        let meta_pairs = parse_meta_tags(meta_tags)?;
        let custom_code_owned: Vec<String> = custom_code.unwrap_or_default();
        let hooks_owned = hooks_body.unwrap_or("").to_string();
        let snapshot = crate::from_wire::build_snapshot_from_wire(bundle, compute_close)?;
        Ok(self.emit_page_and_memo_bodies(
            py,
            snapshot,
            route_ident,
            route,
            title,
            meta_pairs,
            custom_code_owned,
            hooks_owned,
        ))
    }
}

/// Parse the optional `meta_tags` list of `(name, content)` tuples into
/// owned `(String, String)` pairs. Shared by both arena entrypoints.
fn parse_meta_tags(meta_tags: Option<&Bound<'_, PyList>>) -> PyResult<Vec<(String, String)>> {
    match meta_tags {
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
            Ok(out)
        }
        None => Ok(Vec::new()),
    }
}

/// Memoize + emit a frozen snapshot into `(page_js, memo_bodies)`.
///
/// Shared, GIL-released tail of both arena entrypoints
/// (`compile_page_from_component_arena` and `compile_page_from_arena`) so
/// the page module + memo body emit is byte-identical regardless of how
/// the `Snapshot` was sourced (live freeze vs wire rebuild). None of the
/// work here touches Python state.
impl CompilerSession {
    /// Memoize + emit a frozen snapshot into `(page_js, memo_bodies)`,
    /// short-circuiting through the content-addressed page-emit cache
    /// (PR F). On a cache hit the GIL-released memoize + emit is skipped
    /// entirely and the stored output is cloned out; the key
    /// (`compute_emit_cache_key`) hashes every emit input so a hit is
    /// byte-identical to a fresh emit.
    fn emit_page_and_memo_bodies(
        &self,
        py: Python<'_>,
        snapshot: reflex_ir::Snapshot,
        route_ident: &str,
        route: &str,
        title: Option<&str>,
        meta_pairs: Vec<(String, String)>,
        custom_code: Vec<String>,
        hooks_body: String,
    ) -> (String, Vec<(String, String)>) {
        if !self.emit_cache_enabled.get() {
            return emit_page_and_memo_bodies_uncached(
                py,
                snapshot,
                route_ident,
                route,
                title,
                meta_pairs,
                custom_code,
                hooks_body,
            );
        }
        let cache_key = compute_emit_cache_key(
            &snapshot,
            route_ident,
            route,
            title,
            &meta_pairs,
            &custom_code,
            &hooks_body,
        );
        if let Some(hit) = self.page_emit_cache.borrow().get(&cache_key) {
            return hit.clone();
        }
        let result = emit_page_and_memo_bodies_uncached(
            py,
            snapshot,
            route_ident,
            route,
            title,
            meta_pairs,
            custom_code,
            hooks_body,
        );
        self.page_emit_cache
            .borrow_mut()
            .insert(cache_key, result.clone());
        result
    }
}

/// Hash every input the page + memo-body emit reads: the root
/// `subtree_hash` (which recursively folds each node's emit fields), the
/// per-node `vars_used` + `flags` that the close pass doesn't fold, the
/// `var_data` table + dense backings, the side tables emit consults
/// (`app_style_map`, `rename_props`, `special_props`,
/// `add_custom_code_extra`), and the page params. Sound by construction:
/// any change that could alter the emitted JS changes the key.
fn compute_emit_cache_key(
    snap: &reflex_ir::Snapshot,
    route_ident: &str,
    route: &str,
    title: Option<&str>,
    meta_pairs: &[(String, String)],
    custom_code: &[String],
    hooks_body: &str,
) -> u64 {
    use xxhash_rust::xxh3::Xxh3;
    let mut h = Xxh3::new();
    h.update(&(snap.nodes.len() as u64).to_le_bytes());
    h.update(&snap.root.to_le_bytes());
    for node in &snap.nodes {
        h.update(&node.subtree_hash.to_le_bytes());
        h.update(&node.flags.bits().to_le_bytes());
        for r in &node.vars_used {
            h.update(&r.0.to_le_bytes());
        }
    }
    // var_data table + dense backings (content emit references via hooks).
    for e in &snap.var_data {
        h.update(&e.state.as_u32().to_le_bytes());
        h.update(&[e.position]);
    }
    for s in &snap.var_hooks {
        h.update(&s.as_u32().to_le_bytes());
    }
    for (m, n) in &snap.var_imports {
        h.update(&m.as_u32().to_le_bytes());
        h.update(&n.as_u32().to_le_bytes());
    }
    for s in snap.var_deps.iter().chain(snap.var_components.iter()) {
        h.update(&s.as_u32().to_le_bytes());
    }
    // Side tables (sorted for determinism) emit consults.
    let mut style_keys: Vec<_> = snap.app_style_map.iter().collect();
    style_keys.sort_by_key(|(k, _)| k.as_u32());
    for (k, v) in style_keys {
        h.update(&k.as_u32().to_le_bytes());
        h.update(&v.as_u32().to_le_bytes());
    }
    let mut rename_keys: Vec<_> = snap.rename_props.iter().collect();
    rename_keys.sort_by_key(|(k, _)| **k);
    for (idx, pairs) in rename_keys {
        h.update(&idx.to_le_bytes());
        for (a, b) in pairs {
            h.update(&a.as_u32().to_le_bytes());
            h.update(&b.as_u32().to_le_bytes());
        }
    }
    let mut special_keys: Vec<_> = snap.special_props.iter().collect();
    special_keys.sort_by_key(|(k, _)| **k);
    for (idx, syms) in special_keys {
        h.update(&idx.to_le_bytes());
        for s in syms {
            h.update(&s.as_u32().to_le_bytes());
        }
    }
    let mut extra_keys: Vec<_> = snap.add_custom_code_extra.iter().collect();
    extra_keys.sort_by_key(|(k, _)| **k);
    for (idx, syms) in extra_keys {
        h.update(&idx.to_le_bytes());
        for s in syms {
            h.update(&s.as_u32().to_le_bytes());
        }
    }
    // Page params (NUL-separated so concatenations can't alias).
    for part in [route_ident, route, title.unwrap_or(""), hooks_body] {
        h.update(part.as_bytes());
        h.update(&[0]);
    }
    for (k, v) in meta_pairs {
        h.update(k.as_bytes());
        h.update(&[0]);
        h.update(v.as_bytes());
        h.update(&[0]);
    }
    for c in custom_code {
        h.update(c.as_bytes());
        h.update(&[0]);
    }
    h.digest()
}

fn emit_page_and_memo_bodies_uncached(
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

        // Emit each unique memo body. Passthrough signature `"({ children })"`
        // is the default — the arena freeze produces passthrough wrappers
        // only (snapshot-body detection is a follow-on).
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
