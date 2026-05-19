//! `CompilerSession` — the real PyO3 entry point.
//!
//! The Python side keeps a long-lived `CompilerSession` instance across
//! reloads. Two-phase compile: Python builds the IR via
//! `reflex.compiler.ir.bridge.page_to_ir` → bytes; Rust parses + emits
//! via `compile_page_from_bytes` / `compile_memo_from_bytes` with no
//! callbacks into Python during phase 2.
//!
//! A few PyO3 callbacks survive for orchestration *outside* of emit
//! (per-page memoize decision via `should_memoize`, NPM-import harvest
//! for `bun install` via `collect_all_imports*`). They run before the
//! bridge produces bytes, never during emit.

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use reflex_arena::Arena;
use reflex_codegen::{
    emit_app_root_module, emit_context_module, emit_document_root_module, emit_memo_index,
    emit_memo_module, emit_page_with_extras, emit_stateful_pages_json, emit_styles_root,
    emit_theme_module, CodeBuffer,
};
use reflex_ir::parse_page;
use reflex_pyread::{
    collect_all_imports as pyread_collect_all_imports,
    collect_all_imports_into as pyread_collect_all_imports_into,
    merge_imports_into as pyread_merge_imports_into,
    should_memoize as memoize_should_memoize, MemoRefs,
};

/// One per Python `reflex.compiler.session.CompilerSession`. Stateless from
/// Rust's point of view today — the only per-session resources are the
/// thread-local timing/memo-body cells in `reflex_pyread`.
#[pyclass]
pub struct CompilerSession {}

#[pymethods]
impl CompilerSession {
    #[new]
    fn new() -> Self {
        Self {}
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
    fn compile_memo_index(
        &self,
        reexports: Vec<(String, String)>,
        out_path: &str,
    ) -> PyResult<()> {
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
    fn compile_styles_root(
        &self,
        stylesheets: Vec<String>,
        out_path: &str,
    ) -> PyResult<()> {
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
    fn compile_stateful_pages_marker(
        &self,
        routes: Vec<String>,
        out_path: &str,
    ) -> PyResult<()> {
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
        let refs = MemoRefs::new(py)?;
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

    /// Phase-2 memo entry point: compile a memo module from IR bytes.
    ///
    /// Mirror of [`compile_page_from_bytes`] but emits a memo wrapper
    /// module (``export const <name> = memo(<signature> => { ... })``)
    /// instead of a page module. The IR is built by the same
    /// :func:`reflex.compiler.ir.bridge.page_to_ir` over the memo body
    /// Component (with the ``{children}`` hole already substituted at
    /// the Python level for passthrough wrappers).
    ///
    /// Args:
    ///     name: exported memo identifier.
    ///     signature: parameter list spliced after ``memo(`` (e.g.
    ///         ``"({ children })"`` for passthroughs, ``"()"`` for
    ///         snapshot bodies).
    ///     ir_bytes: msgpack-packed IR for the memo body.
    ///     pre_hooks: optional pre-rendered hook block harvested by
    ///         Python (color-mode destructure, custom hooks).
    #[pyo3(signature = (name, signature, ir_bytes, pre_hooks=""))]
    fn compile_memo_from_bytes(
        &self,
        py: Python<'_>,
        name: &str,
        signature: &str,
        ir_bytes: &Bound<'_, PyBytes>,
        pre_hooks: &str,
    ) -> PyResult<String> {
        let buf = ir_bytes.as_bytes().to_vec();
        let name_owned = name.to_string();
        let signature_owned = signature.to_string();
        let pre_hooks_owned = pre_hooks.to_string();
        py.allow_threads(|| -> PyResult<String> {
            let arena = Arena::new();
            let page = parse_page(&arena, &buf).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("ir parse failed: {e}"))
            })?;
            let mut out = CodeBuffer::with_capacity(1024);
            emit_memo_module(&mut out, &page, &name_owned, &signature_owned, &pre_hooks_owned);
            String::from_utf8(out.into_bytes()).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "rust emit produced non-utf8: {e}"
                ))
            })
        })
    }

    /// Phase-2 entry point: compile a page from already-serialized IR bytes.
    ///
    /// Pure two-phase model — Python produced the bytes via
    /// `reflex.compiler.ir.bridge.page_to_ir`; this method parses the
    /// msgpack into an in-arena `Page` and runs the same JSX emitter the
    /// pyread path uses. **No PyO3 callbacks during emit**: route, title,
    /// meta, component imports, state bindings, needs_ref are all read
    /// from the IR itself. The GIL is released for the parse + emit
    /// span so multiple pages can be compiled concurrently from
    /// different threads.
    ///
    /// Args:
    ///     route_ident: JS identifier used for the route export.
    ///     ir_bytes: msgpack-packed Page IR (schema v2).
    ///     custom_code: optional pre-rendered custom-code blocks.
    ///     hooks_body: optional pre-rendered hooks body string.
    #[pyo3(signature = (route_ident, ir_bytes, custom_code=None, hooks_body=None))]
    fn compile_page_from_bytes(
        &self,
        py: Python<'_>,
        route_ident: &str,
        ir_bytes: &Bound<'_, PyBytes>,
        custom_code: Option<Vec<String>>,
        hooks_body: Option<&str>,
    ) -> PyResult<String> {
        let custom_code_owned: Vec<String> = custom_code.unwrap_or_default();
        let hooks_owned = hooks_body.unwrap_or("").to_string();
        // Copy the bytes out so we can drop the GIL before parsing — the
        // parse + emit path is pure Rust and benefits from running while
        // the next page is being serialized on the Python side.
        let buf = ir_bytes.as_bytes().to_vec();

        py.allow_threads(|| -> PyResult<String> {
            let arena = Arena::new();
            let page = parse_page(&arena, &buf).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("ir parse failed: {e}"))
            })?;
            let custom_code_refs: Vec<&str> =
                custom_code_owned.iter().map(String::as_str).collect();
            let mut out = CodeBuffer::with_capacity(1024);
            emit_page_with_extras(&mut out, &page, route_ident, &custom_code_refs, &hooks_owned);
            String::from_utf8(out.into_bytes()).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "rust emit produced non-utf8: {e}"
                ))
            })
        })
    }
}

/// Open `out_path` for buffered write and run `f` on the writer, mapping
/// any `io::Error` into a Python `OSError`.
///
/// Used by every "build content + write to disk" PyO3 method on
/// `CompilerSession` so the buffering, error mapping, and flush
/// behaviour stay consistent across the whole static-artifact surface.
fn write_to_file<F>(out_path: &str, f: F) -> PyResult<()>
where
    F: FnOnce(&mut std::io::BufWriter<std::fs::File>) -> std::io::Result<()>,
{
    let file = std::fs::File::create(out_path)
        .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("{out_path}: {e}")))?;
    let mut w = std::io::BufWriter::new(file);
    f(&mut w).map_err(|e| pyo3::exceptions::PyOSError::new_err(e.to_string()))?;
    std::io::Write::flush(&mut w)
        .map_err(|e| pyo3::exceptions::PyOSError::new_err(e.to_string()))
}
