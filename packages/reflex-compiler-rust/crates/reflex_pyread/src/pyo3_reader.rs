//! PyO3 walk over a Reflex `Component` PyObject → `reflex_ir::Page<'arena>`.
//!
//! Mirrors `reflex/compiler/ir/bridge.py` one-for-one. Every supported
//! Component subclass dispatches on `type(component).__name__`; props,
//! events, and child references go through PyO3 `getattr` calls.
//!
//! Coverage matches the bridge's: Bare, Fragment, Cond, Foreach, Match,
//! and generic Element. CustomComponent and memo-wrapper subclasses fall
//! through to the generic Element path the same way the bridge does.
//!
//! Var values produce `Value::JsExpr { expr, var_data }` — the same shape
//! the msgpack parser builds — so downstream codegen needs no changes.

use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet};

use pyo3::prelude::*;
use pyo3::types::{
    PyAnyMethods, PyBool, PyDict, PyFloat, PyInt, PyList, PyMapping, PyString, PyStringMethods,
    PyTuple, PyTypeMethods,
};

use reflex_arena::Arena;
use reflex_intern::{intern, Symbol};
use reflex_ir::{
    Component, EventHandler, Hook, Literal, MatchArm, Meta, NodeId, Page, PyFileId, SourceLoc,
    Value, VarData,
};

use super::text::decode_js_string_literal;
use super::timing::{self, Counter as TC, Field as TF, Span as TSpan};

/// Wire schema version this reader emits. Matches `reflex_ir::parse`'s
/// `SCHEMA_VERSION`. The reader doesn't go through msgpack, but downstream
/// codegen branches on `Page.schema_version`.
const SCHEMA_VERSION: u32 = 2;

/// Errors raised by the PyO3 component reader.
///
/// Surfaced as Python `ValueError`s via `CompilerSession`. They carry
/// enough context to map back to the originating Component without a
/// stack trace.
#[derive(Debug, thiserror::Error)]
pub enum PyReadError {
    #[error("pyo3 attribute error on `{attr}`: {source}")]
    Attr {
        attr: &'static str,
        #[source]
        source: PyErr,
    },
    #[error("pyread does not yet support Component subclass `{class}`")]
    Unsupported { class: String },
    #[error("pyread type error on `{attr}`: expected {expected}, got {got}")]
    TypeMismatch {
        attr: &'static str,
        expected: &'static str,
        got: String,
    },
}

impl From<PyReadError> for PyErr {
    fn from(e: PyReadError) -> Self {
        pyo3::exceptions::PyValueError::new_err(e.to_string())
    }
}

/// Cached PyObject handles the reader needs on the hot path.
///
/// Resolved once per `read_page` call instead of per node — the
/// `import_bound` lookup is ~10 µs but `is_instance` against a cached
/// class is ~100 ns. With ~165 nodes/page and ~5 isinstance checks each,
/// caching saves ~8 ms.
pub struct PyRefs<'py> {
    pub var_cls: Bound<'py, PyAny>,
    pub literal_var_cls: Bound<'py, PyAny>,
    /// `reflex_base.utils.format.format_library_name` for normalizing
    /// `Component.library` and `VarData.imports` module specifiers.
    pub format_library_name: Bound<'py, PyAny>,
    /// `reflex_base.style.format_as_emotion` — the CSS-in-JS transform the
    /// base `Component._get_style` applies before wrapping in a `LiteralVar`.
    /// `read_style` calls this directly and renders the resulting object
    /// literal in Rust, skipping the per-property `LiteralVar.create` churn.
    pub format_as_emotion: Bound<'py, PyAny>,
    /// The base `Component._get_style` (unbound function). `read_style`
    /// fast-paths only nodes whose class does NOT override it; overrides
    /// (e.g. recharts' `{"wrapperStyle": ...}`) go through `_get_style`.
    pub component_get_style_base: Bound<'py, PyAny>,
    /// `Component._exclude_props` — identity baseline so the freeze only
    /// calls the override on classes that actually exclude props.
    pub component_exclude_props_base: Bound<'py, PyAny>,
    /// `Component._render` — identity baseline; override classes take the
    /// rendered-Tag prop path.
    pub component_render_base: Bound<'py, PyAny>,
    /// `reflex_base.constants.compiler.Imports.EVENTS` — the constant import
    /// dict `_get_imports` adds when a component has event triggers.
    pub events_imports: Bound<'py, PyAny>,
    /// `component._REF_HOOK_IMPORTS` — the ref hook's constant import dict
    /// (react.useRef + $/utils/state.refs).
    pub ref_hook_imports: Bound<'py, PyAny>,
    /// `component._LIFECYCLE_HOOK_IMPORTS` — the mount/unmount lifecycle
    /// hook's constant import dict (react.useEffect).
    pub lifecycle_hook_imports: Bound<'py, PyAny>,
    /// `Component._get_app_wrap_components` — identity baseline so the
    /// freeze only calls the override on classes that declare app wraps.
    pub component_app_wrap_base: Bound<'py, PyAny>,
    /// `reflex_base.utils.imports.parse_imports` — normalizes `add_imports()`
    /// results into the `{lib: [ImportVar]}` shape before merging.
    pub parse_imports: Bound<'py, PyAny>,
    /// The `dict` builtin — replicates `_get_imports`' `dict(var_data.imports)`
    /// (tuple-of-pairs → last-wins dict) byte-for-byte.
    pub dict_builtin: Bound<'py, PyAny>,
    /// The base `Component._get_imports` (unbound function). The Rust import
    /// builder reproduces only the BASE formula; classes that override
    /// `_get_imports` (e.g. `NoSSRComponent` rewrites the library import) must
    /// call their override. Sub-method overrides (`add_imports`, …) are fine —
    /// the builder invokes them.
    pub component_get_imports_base: Bound<'py, PyAny>,
    /// `reflex_base.components.component.ComponentField` — the non-data
    /// descriptor class fields resolve through since the sparse-`__dict__`
    /// cutover. `read_field` only trusts a cached class-level default when
    /// the class attribute under that name IS a `ComponentField`; anything
    /// else (`@property`, plain attribute) keeps real getattr semantics.
    pub component_field_cls: Bound<'py, PyAny>,
    /// `reflex_base.breakpoints.Breakpoints` — the responsive-style dict
    /// subclass `format_as_emotion` special-cases. Used by the Rust
    /// emotion transform's value dispatch.
    pub breakpoints_cls: Bound<'py, PyAny>,
    /// The native `RustVar` pyclass type object plus its `_js_expr` /
    /// `_get_all_var_data` descriptors. The freeze pass reads native Vars'
    /// Rust fields directly (no Python attribute protocol); a subclass is
    /// only eligible when its descriptors are identical to the base ones
    /// (cached per class) — an override keeps the generic Python path.
    pub rustvar_type: Bound<'py, PyAny>,
    pub rustvar_js_expr_desc: Bound<'py, PyAny>,
    pub rustvar_gavd_desc: Bound<'py, PyAny>,
    /// `reflex_base.breakpoints.breakpoints_values` — the MUTABLE global
    /// list (`set_breakpoints` clears+extends it in place, so holding the
    /// list object stays correct). Read on each responsive-list style so
    /// user overrides apply.
    pub breakpoints_values: Bound<'py, PyAny>,
    /// Page-level harvests accumulated inline during `read_page` so we
    /// don't have to re-walk the Python tree again for
    /// `component_imports` / `state_bindings`. Interior
    /// mutability keeps the read helpers' `&PyRefs` signatures intact;
    /// every borrow is scoped to a single registration to avoid
    /// runtime aliasing panics.
    pub harvest: RefCell<HarvestState>,
    /// Per-class memoization metadata cache keyed by `type(component) as *const _`.
    /// Avoids repeated `_memoization_mode.disposition` / `recursive` getattr
    /// chains for nodes of the same class. First lookup populates; later
    /// nodes hit a HashMap with the cached `(disposition_byte, recursive)`
    /// pair.
    ///
    /// **Note (B)**: this cache is per-call (lives on PyRefs). For
    /// the cross-call class-metadata cache, see ``class_cache`` —
    /// when set, lookups go through there instead, and this field
    /// stays a per-call fallback.
    pub memo_mode_cache: RefCell<HashMap<usize, MemoModeCached>>,
    /// B/C: session-scoped class cache. ``None`` for callers that
    /// don't supply one (legacy `read_page` path); freezes from
    /// `compile_page_from_component_arena` clone the session's Rc
    /// so per-class metadata survives across compiles.
    pub class_cache: Option<std::rc::Rc<RefCell<ClassMetadataCache>>>,
    /// Out-counters incremented by the freeze pass:
    /// * boundary-crossing count → `freeze_pyo3_call_count` (A)
    /// * trivial-skip count → `freeze_trivial_skip_count` (C)
    /// * direct-from-Rust call counts for `get_props` and
    ///   `_rename_props` → `direct_get_props_calls` /
    ///   `direct_rename_props_reads` (B). These exclude calls
    ///   triggered by Python's own internal chains (e.g.
    ///   `_get_imports` → `_get_vars` → `get_props`) which our
    ///   per-class cache can't suppress.
    pub freeze_crossings_counter: Option<std::rc::Rc<Cell<u64>>>,
    pub freeze_trivial_skips_counter: Option<std::rc::Rc<Cell<u64>>>,
    pub direct_get_props_calls: Option<std::rc::Rc<Cell<u64>>>,
    pub direct_rename_props_reads: Option<std::rc::Rc<Cell<u64>>>,
    /// A: cached reference to the ``reflex_compiler_rust._native``
    /// module object. The batched ``_arena_freeze_extract`` function
    /// is looked up off this each visit so
    /// ``patch.object(_native, "_arena_freeze_extract", wrapper)``
    /// in tests intercepts our calls. Holding the module (not the
    /// function) lets the test patches take effect — but for
    /// performance we cache the resolved function reference per call
    /// in `arena_freeze_extract_fn` below and only re-resolve when
    /// the module attribute changes (which happens during patching).
    pub native_module: Option<Py<PyAny>>,
    /// PR7 var-data dedup table. Maps ``id(var)`` → index into
    /// ``Snapshot.var_data``. First time a Var is observed during the
    /// freeze walk, a ``VarDataEntry`` is built and pushed; subsequent
    /// observations reuse the same index. Scoped per ``freeze_component``
    /// call so cross-page caching doesn't leak.
    pub var_data_dedup: RefCell<HashMap<usize, u32>>,
    /// PR7 follow-through: bun-install imports accumulator harvested
    /// inline during freeze. Each Component visited contributes its
    /// ``_get_imports()`` entries to this ``dict[str, list[ImportVar]]``
    /// (alias-prefix transform applied), and ``_get_components_in_props``
    /// recursion catches Components embedded in Var values that the
    /// snapshot tree walk doesn't visit. Visited components are
    /// tracked in ``imports_seen`` so `_get_imports` runs at most
    /// once per Component per ``freeze_component`` call — eliminates
    /// the separate ``collect_all_imports`` tree walk.
    pub bun_imports: RefCell<Option<Py<PyDict>>>,
    pub imports_seen: RefCell<HashSet<usize>>,
    /// App-wrap accumulator harvested inline during freeze: the
    /// `{(priority, name): Component}` dict that
    /// `_get_all_app_wrap_components` used to compute with a second
    /// Python tree walk. Only classes overriding the base staticmethod
    /// contribute (per-class expanded dict cached on `ClassMetadata`),
    /// merged at most once per class per freeze via `app_wraps_seen`.
    /// `None` for callers that don't need wraps (memo freezes).
    pub app_wraps: RefCell<Option<Py<PyDict>>>,
    pub app_wraps_seen: RefCell<HashSet<usize>>,
    /// Pre-interned attribute / method names. Each PyO3 ``getattr``
    /// or ``call_method0`` that took ``&str`` previously allocated a
    /// fresh ``PyString`` per call; passing the pre-interned
    /// ``Bound<PyString>`` here lets the Python attribute lookup hit
    /// its fast path. ~50-100 ns saved per access on the hot path.
    pub attrs: InternedAttrs,
    /// Per-class method handle cache for the heavy
    /// ``call_method0``-style methods (``_get_imports``,
    /// ``_get_components_in_props``, ``_get_hooks_internal``,
    /// ``_get_hooks_user``, ``_get_app_wrap_components``,
    /// ``_get_all_dynamic_imports``, ``_get_all_custom_code``,
    /// ``get_props``, ``_render``). Keyed by
    /// ``type(component) as *const _``; values are pre-resolved
    /// unbound functions ready for ``call1((obj,))``. Skips the
    /// MRO walk that ``call_method0`` runs on every invocation.
    pub method_cache: RefCell<HashMap<usize, ClassMethodHandles>>,
}

/// Pre-interned attribute / method-name `PyString`s. Built once at
/// `PyRefs::new` and reused on every Component visited in freeze.
/// Mirrors Pydantic v2's `intern!` discipline: any string used as a
/// `getattr` key is held as a stable `Py<PyString>` so Python's
/// attribute lookup skips the `&str → PyString` allocation.
pub struct InternedAttrs {
    // Component structural attrs
    pub tag: Py<PyString>,
    pub alias: Py<PyString>,
    pub library: Py<PyString>,
    pub is_tag_in_global_scope: Py<PyString>,
    pub children: Py<PyString>,
    pub iterable: Py<PyString>,
    pub contents: Py<PyString>,
    pub event_triggers: Py<PyString>,
    pub custom_attrs: Py<PyString>,
    pub key: Py<PyString>,
    pub id: Py<PyString>,
    pub class_name: Py<PyString>,
    pub style: Py<PyString>,
    pub dunder_dict: Py<PyString>,
    pub lib_dependencies: Py<PyString>,
    pub special_props: Py<PyString>,
    pub import_var: Py<PyString>,
    pub qualname: Py<PyString>,
    pub rename_props: Py<PyString>,
    pub memoization_mode: Py<PyString>,
    pub disposition: Py<PyString>,
    pub value: Py<PyString>,
    pub recursive: Py<PyString>,
    pub cond: Py<PyString>,
    pub js_expr: Py<PyString>,
    // Var-data attrs
    pub state: Py<PyString>,
    pub hooks: Py<PyString>,
    pub components: Py<PyString>,
    pub deps: Py<PyString>,
    pub imports: Py<PyString>,
    pub position: Py<PyString>,
    pub render: Py<PyString>,
    pub tag_attr: Py<PyString>,
    // Method names
    pub m_get_imports: Py<PyString>,
    pub m_get_components_in_props: Py<PyString>,
    pub m_get_hooks_internal: Py<PyString>,
    pub m_get_hooks_user: Py<PyString>,
    pub m_get_app_wrap_components: Py<PyString>,
    pub m_get_all_dynamic_imports: Py<PyString>,
    pub m_get_all_custom_code: Py<PyString>,
    pub m_get_props: Py<PyString>,
    pub m_get_all_var_data: Py<PyString>,
    pub m_get_style: Py<PyString>,
    pub m_render: Py<PyString>,
    pub m_render_component: Py<PyString>,
    pub m_get_vars: Py<PyString>,
    pub m_get_custom_code: Py<PyString>,
    pub m_get_dynamic_imports: Py<PyString>,
    pub m_get_hooks: Py<PyString>,
    pub m_get_added_hooks: Py<PyString>,
    pub m_iter_parent_classes_with_method: Py<PyString>,
    pub m_default_value: Py<PyString>,
}

impl InternedAttrs {
    fn new(py: Python<'_>) -> Self {
        let s = |name: &str| -> Py<PyString> { PyString::new_bound(py, name).unbind() };
        Self {
            tag: s("tag"),
            alias: s("alias"),
            library: s("library"),
            is_tag_in_global_scope: s("_is_tag_in_global_scope"),
            children: s("children"),
            iterable: s("iterable"),
            contents: s("contents"),
            event_triggers: s("event_triggers"),
            custom_attrs: s("custom_attrs"),
            key: s("key"),
            id: s("id"),
            class_name: s("class_name"),
            style: s("style"),
            dunder_dict: s("__dict__"),
            lib_dependencies: s("lib_dependencies"),
            special_props: s("special_props"),
            import_var: s("import_var"),
            qualname: s("__qualname__"),
            rename_props: s("_rename_props"),
            memoization_mode: s("_memoization_mode"),
            disposition: s("disposition"),
            value: s("value"),
            recursive: s("recursive"),
            cond: s("cond"),
            js_expr: s("_js_expr"),
            state: s("state"),
            hooks: s("hooks"),
            components: s("components"),
            deps: s("deps"),
            imports: s("imports"),
            position: s("position"),
            render: s("render"),
            tag_attr: s("tag"),
            m_get_imports: s("_get_imports"),
            m_get_components_in_props: s("_get_components_in_props"),
            m_get_hooks_internal: s("_get_hooks_internal"),
            m_get_hooks_user: s("_get_hooks_user"),
            m_get_app_wrap_components: s("_get_app_wrap_components"),
            m_get_all_dynamic_imports: s("_get_all_dynamic_imports"),
            m_get_all_custom_code: s("_get_all_custom_code"),
            m_get_props: s("get_props"),
            m_get_all_var_data: s("_get_all_var_data"),
            m_get_style: s("_get_style"),
            m_render: s("_render"),
            m_render_component: s("render_component"),
            m_get_vars: s("_get_vars"),
            m_get_custom_code: s("_get_custom_code"),
            m_get_dynamic_imports: s("_get_dynamic_imports"),
            m_get_hooks: s("_get_hooks"),
            m_get_added_hooks: s("_get_added_hooks"),
            m_iter_parent_classes_with_method: s("_iter_parent_classes_with_method"),
            m_default_value: s("default_value"),
        }
    }
}

/// Per-class cached method handles. Each `Option<Py<PyAny>>` is the
/// unbound method object resolved from the class once on first
/// encounter; subsequent invocations call it via `call1((obj,))`,
/// skipping the per-call MRO walk and bound-method allocation that
/// `obj.call_method0("name")` performs.
#[derive(Default)]
pub struct ClassMethodHandles {
    pub get_imports: Option<Py<PyAny>>,
    pub get_components_in_props: Option<Py<PyAny>>,
    pub get_hooks_internal: Option<Py<PyAny>>,
    pub get_hooks_user: Option<Py<PyAny>>,
    pub get_app_wrap_components: Option<Py<PyAny>>,
    pub get_all_dynamic_imports: Option<Py<PyAny>>,
    pub get_all_custom_code: Option<Py<PyAny>>,
    pub get_props: Option<Py<PyAny>>,
    pub render: Option<Py<PyAny>>,
    pub get_custom_code: Option<Py<PyAny>>,
    pub get_dynamic_imports: Option<Py<PyAny>>,
    pub get_hooks: Option<Py<PyAny>>,
    pub get_added_hooks: Option<Py<PyAny>>,
    pub get_style: Option<Py<PyAny>>,
    pub get_all_var_data: Option<Py<PyAny>>,
}

// ---- B/C: long-lived per-class metadata cache ----------------------------

/// Optional `_get_*` methods that often return trivial values (empty
/// dict / None / empty string) for a given Component class. The
/// skip-list cache (planx.md option C) marks a class+method pair
/// "skip" after a warmup window and elides the call on future
/// instances of that class.
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SkippableMethod {
    GetAddedHooks = 0,
    GetDynamicImports = 1,
    GetHooks = 2,
    GetCustomCode = 3,
    GetComponentsInProps = 4,
    GetAppWrapComponents = 5,
}

impl SkippableMethod {
    pub const COUNT: usize = 6;
    #[inline]
    pub const fn bit(self) -> u8 {
        1 << (self as u8)
    }
}

/// Long-lived per-Component-class metadata. Owned by ``CompilerSession``
/// (not ``PyRefs``) so the cache survives across compiles — that's what
/// makes the warm-vs-cold session timings diverge after B lands.
///
/// Entries are populated lazily on first encounter with a class. After
/// population, every subsequent same-class node skips:
///
/// * ``get_props()`` invocation — ``prop_names`` is the cached result.
/// * ``_rename_props`` getattr — ``rename_props`` holds the resolved
///   `(old, new)` pairs.
/// * ``_memoization_mode.{disposition,recursive}`` getattr chain —
///   ``memo_mode`` carries the resolved triple.
/// * Bound-method MRO walks for the heavy `_get_*` callbacks —
///   ``method_handles`` caches each unbound method.
/// * Probes of optional methods this class is known to return trivial
///   values for — ``skip_flags`` bits set after warmup.
pub struct ClassMetadata {
    /// `get_props()` result as a fully-resolved list of
    /// `(attr_name, interned_pystring)`. The interned name is reused
    /// by the per-instance prop reader without re-walking
    /// `get_props`. ``None`` until first observation.
    pub prop_names: Option<Vec<(String, Py<PyString>)>>,
    /// B: per-field class-level default, resolved lazily the first
    /// time `read_field` misses the instance `__dict__` for that
    /// `(class, field)`. Keyed by the raw (unstripped) field name.
    pub field_defaults: HashMap<String, FieldDefault>,
    /// `_rename_props` resolved once per class.
    pub rename_props: smallvec::SmallVec<[(Symbol, Symbol); 1]>,
    /// `_rename_props` cache populated bit (covers the empty-result
    /// case which ``rename_props`` alone can't distinguish from
    /// "not yet populated").
    pub rename_props_resolved: bool,
    /// `_memoization_mode` triple (disposition, recursive, is_foreach).
    pub memo_mode: Option<MemoModeCached>,
    /// Method-handle cache for heavy callbacks. Survives across
    /// compiles in the same session.
    pub method_handles: ClassMethodHandles,
    /// Whether this class can use the generic static import path for
    /// trivial instances. ``None`` until first observation.
    pub default_imports_safe: Option<bool>,
    /// Whether `_get_style` on this class is the base implementation
    /// (drives the Rust emotion path). ``None`` until first observation.
    pub style_is_base: Option<bool>,
    /// Whether `_get_imports` on this class is the base implementation
    /// (drives the Rust `build_imports_dict` path).
    pub imports_is_base: Option<bool>,
    /// Whether instances of this (Var) class can be read directly as
    /// native `RustVar` structs: exact `RustVar`, or a subclass whose
    /// `_js_expr` / `_get_all_var_data` descriptors are the base ones.
    pub rustvar_direct: Option<bool>,
    /// Whether this class's ``add_custom_code`` MRO chain is empty
    /// (the common case — skips the per-node chain walk entirely).
    pub add_custom_code_chain_empty: Option<bool>,
    /// Whether `_exclude_props` on this class is the base implementation
    /// (returns nothing — skips the per-node exclusion call).
    pub exclude_props_is_base: Option<bool>,
    /// Whether `_render` on this class is the base implementation. Classes
    /// that override it mutate the prop set imperatively, so the freeze
    /// sources props/events from the rendered Tag instead of raw fields.
    pub render_is_base: Option<bool>,
    /// Whether `_get_app_wrap_components` on this class is the base
    /// staticmethod (returns `{}` — the common case, skipped entirely).
    pub app_wrap_is_base: Option<bool>,
    /// For override classes: the expanded `{(priority, name): Component}`
    /// dict (own wraps plus wraps-of-wraps), computed once per class.
    /// The staticmethod's output is instance-independent, and `_app_root`
    /// deepcopies wrappers before mutating, so sharing one instance per
    /// class across nodes and pages is safe.
    pub app_wraps_dict: Option<Py<PyAny>>,
    /// Bitmask of methods that have been marked "always trivial" for
    /// this class. One bit per `SkippableMethod` variant.
    pub skip_flags: u8,
    /// Count of consecutive trivial returns observed per
    /// ``SkippableMethod``. Once a counter reaches the warmup
    /// threshold, the corresponding ``skip_flags`` bit gets set.
    pub trivial_counts: [u8; SkippableMethod::COUNT],
    /// Total instance visits since cache entry was created (or last
    /// revalidation). When this hits `REVALIDATE_EVERY_N`, all
    /// ``skip_flags`` and ``trivial_counts`` reset so a class that
    /// changed behavior gets re-probed.
    pub total_visits: u32,
}

/// B: how an unset field resolves at the class level. Mirrors what the
/// `ComponentField` non-data descriptor would do on instance getattr,
/// without the per-node Python `__get__` invocation (~1 µs each).
pub enum FieldDefault {
    /// Class attr is a `ComponentField` with a resolvable default —
    /// `default_value()` result cached. For factory defaults this shares
    /// one materialized value across instances; freeze only reads, and
    /// the descriptor's shared-scalar path has the same semantics.
    Value(Py<PyAny>),
    /// Class attr absent, or `default_value()` raised (no default and no
    /// factory) — instance getattr would raise `AttributeError`.
    Missing,
    /// Class attr is NOT a `ComponentField` (`@property`, method, plain
    /// attribute): always do the real instance getattr.
    Dynamic,
}

impl Default for ClassMetadata {
    fn default() -> Self {
        Self {
            prop_names: None,
            field_defaults: HashMap::new(),
            rename_props: smallvec::SmallVec::new(),
            rename_props_resolved: false,
            memo_mode: None,
            method_handles: ClassMethodHandles::default(),
            default_imports_safe: None,
            style_is_base: None,
            imports_is_base: None,
            rustvar_direct: None,
            add_custom_code_chain_empty: None,
            exclude_props_is_base: None,
            render_is_base: None,
            app_wrap_is_base: None,
            app_wraps_dict: None,
            skip_flags: 0,
            trivial_counts: [0; SkippableMethod::COUNT],
            total_visits: 0,
        }
    }
}

// ---- B: sparse-`__dict__` field reads -------------------------------------

/// B: the component's instance `__dict__`, fetched once per call site.
/// Since the sparse-`__init__` cutover this holds ONLY explicitly-set
/// fields (~6 keys vs ~24), so a `PyDict_GetItem` probe replaces the
/// descriptor-protocol getattr for the common unset-field case.
pub(crate) fn instance_dict<'py>(
    component: &Bound<'py, PyAny>,
    refs: &PyRefs<'py>,
) -> Option<Bound<'py, PyDict>> {
    let py = component.py();
    component
        .getattr(refs.attrs.dunder_dict.bind(py))
        .ok()
        .and_then(|d| d.downcast_into::<PyDict>().ok())
}

/// What an unset field resolves to for this read, borrowed out of the
/// per-class cache (or freshly resolved on first miss).
enum FieldDefaultLookup<'py> {
    Value(Bound<'py, PyAny>),
    Missing,
    Dynamic,
}

/// B: resolve the class-level default for `raw` once per `(class, field)`
/// and cache it. Only a class attribute that IS a `ComponentField` may be
/// cached as a value/missing — anything else (a `@property` under a field
/// name, a plain class attr) stays `Dynamic` and keeps real getattr
/// semantics. The resolution mirrors `ComponentField.__get__`:
/// `default_value()` when it has a default or factory, `AttributeError`
/// (here: `Missing`) otherwise.
fn class_field_default<'py>(
    component: &Bound<'py, PyAny>,
    raw: &str,
    interned: &Py<PyString>,
    refs: &PyRefs<'py>,
) -> FieldDefaultLookup<'py> {
    let py = component.py();
    let Some(cache_rc) = &refs.class_cache else {
        return FieldDefaultLookup::Dynamic;
    };
    let ty = component.get_type();
    let key = ty.as_ptr() as usize;
    {
        let cache = cache_rc.borrow();
        if let Some(meta) = cache.get(&key) {
            if let Some(fd) = meta.field_defaults.get(raw) {
                return match fd {
                    FieldDefault::Value(v) => FieldDefaultLookup::Value(v.bind(py).clone()),
                    FieldDefault::Missing => FieldDefaultLookup::Missing,
                    FieldDefault::Dynamic => FieldDefaultLookup::Dynamic,
                };
            }
        }
    }
    // Resolve outside the borrow — `default_value()` runs Python.
    // Class access on a non-data descriptor returns the descriptor
    // itself (`ComponentField.__get__(None, cls) -> self`). Since
    // `_finalize_fields` installs scalar defaults as plain class attrs,
    // a non-descriptor class attribute under a field name IS the
    // default — cache it directly. Descriptors other than
    // `ComponentField` (`@property`, functions) stay `Dynamic`.
    let resolved = match ty.getattr(interned.bind(py)) {
        Err(_) => FieldDefault::Missing,
        Ok(attr) => {
            if attr.is_instance(&refs.component_field_cls).unwrap_or(false) {
                match attr.call_method0(refs.attrs.m_default_value.bind(py)) {
                    Ok(v) => FieldDefault::Value(v.unbind()),
                    Err(_) => FieldDefault::Missing,
                }
            } else if attr.get_type().hasattr("__get__").unwrap_or(true) {
                FieldDefault::Dynamic
            } else {
                FieldDefault::Value(attr.unbind())
            }
        }
    };
    let out = match &resolved {
        FieldDefault::Value(v) => FieldDefaultLookup::Value(v.bind(py).clone()),
        FieldDefault::Missing => FieldDefaultLookup::Missing,
        FieldDefault::Dynamic => FieldDefaultLookup::Dynamic,
    };
    cache_rc
        .borrow_mut()
        .entry(key)
        .or_default()
        .field_defaults
        .insert(raw.to_owned(), resolved);
    out
}

/// B: read a declared field without invoking the `ComponentField`
/// descriptor for unset fields: probe the instance `__dict__`, then fall
/// back to the cached per-class default. `None` means "attribute absent"
/// (the call-site equivalent of a getattr `Err`); a present-but-`None`
/// Python value comes back as `Some(none)` exactly like getattr would.
pub(crate) fn read_field<'py>(
    component: &Bound<'py, PyAny>,
    inst_dict: Option<&Bound<'py, PyDict>>,
    raw: &str,
    interned: &Py<PyString>,
    refs: &PyRefs<'py>,
) -> Option<Bound<'py, PyAny>> {
    let py = component.py();
    if let Some(d) = inst_dict {
        if let Ok(Some(v)) = d.get_item(interned.bind(py)) {
            return Some(v);
        }
        match class_field_default(component, raw, interned, refs) {
            FieldDefaultLookup::Value(v) => return Some(v),
            FieldDefaultLookup::Missing => return None,
            FieldDefaultLookup::Dynamic => {}
        }
    }
    component.getattr(interned.bind(py)).ok()
}

/// Warmup threshold: after this many consecutive trivial returns for
/// a `(class, method)` pair, the method is added to the skip-list.
/// Three matches the heuristic in planx.md: small enough to engage on
/// realistic pages, large enough to avoid false-positives on a single
/// unusual instance.
pub const TRIVIAL_WARMUP_THRESHOLD: u8 = 3;

/// Revalidation interval. After every N visits to a class, reset its
/// skip-list state so a class that flipped trivial → non-trivial
/// (e.g. user-mutated metaprogramming) gets re-probed.
pub const REVALIDATE_EVERY_N: u32 = 100;

/// `HashMap<*const PyType as usize, ClassMetadata>`. Wrapped on the
/// session in a `RefCell` so freeze can mutate it under interior
/// mutability while the snapshot builder holds other references.
pub type ClassMetadataCache = std::collections::HashMap<usize, ClassMetadata>;

/// Cached per-class memoization metadata; one entry per `type(component)`.
///
/// `disposition_byte` is `0` (Auto/STATEFUL), `1` (Never), or `2` (Always);
/// it maps 1:1 onto `reflex_ir::MemoizationDisposition`. `recursive=false`
/// makes the class a snapshot boundary.
#[derive(Clone, Copy, Debug)]
pub struct MemoModeCached {
    pub disposition_byte: u8,
    pub recursive: bool,
    pub is_foreach: bool,
}

/// Page-level data the bridge collects during `read_page`. Equivalent to
/// what `collect_component_imports` / `collect_state_bindings` used to
/// compute in separate walks; now accumulated in one pass by the read
/// helpers as they visit each node.
#[derive(Default)]
pub struct HarvestState {
    component_imports: Vec<(Symbol, Symbol)>,
    component_imports_seen: HashSet<(Symbol, Symbol)>,
    state_bindings: Vec<Symbol>,
    state_bindings_seen: HashSet<String>,
}

impl HarvestState {
    pub fn add_component_import(&mut self, pair: (Symbol, Symbol)) {
        if self.component_imports_seen.insert(pair) {
            self.component_imports.push(pair);
        }
    }

    pub fn add_state_idents_in(&mut self, expr: &str) {
        for ident in find_state_idents(expr) {
            if self.state_bindings_seen.insert(ident.clone()) {
                self.state_bindings.push(intern(&ident));
            }
        }
    }
}

impl<'py> PyRefs<'py> {
    pub fn new(py: Python<'py>) -> Result<Self, PyReadError> {
        let vars_mod =
            py.import_bound("reflex_base.vars.base")
                .map_err(|source| PyReadError::Attr {
                    attr: "import reflex_base.vars.base",
                    source,
                })?;
        let var_cls = vars_mod
            .getattr("Var")
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.vars.base.Var",
                source,
            })?;
        let literal_var_cls =
            vars_mod
                .getattr("LiteralVar")
                .map_err(|source| PyReadError::Attr {
                    attr: "reflex_base.vars.base.LiteralVar",
                    source,
                })?;
        let format_library_name = py
            .import_bound("reflex_base.utils.format")
            .and_then(|m| m.getattr("format_library_name"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.utils.format.format_library_name",
                source,
            })?;
        let format_as_emotion = py
            .import_bound("reflex_base.style")
            .and_then(|m| m.getattr("format_as_emotion"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.style.format_as_emotion",
                source,
            })?;
        let component_exclude_props_base = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("Component"))
            .and_then(|c| c.getattr("_exclude_props"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.Component._exclude_props",
                source,
            })?;
        let component_render_base = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("Component"))
            .and_then(|c| c.getattr("_render"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.Component._render",
                source,
            })?;
        let component_get_style_base = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("Component"))
            .and_then(|c| c.getattr("_get_style"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.Component._get_style",
                source,
            })?;
        let events_imports = py
            .import_bound("reflex_base.constants.compiler")
            .and_then(|m| m.getattr("Imports"))
            .and_then(|i| i.getattr("EVENTS"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.constants.compiler.Imports.EVENTS",
                source,
            })?;
        let ref_hook_imports = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("_REF_HOOK_IMPORTS"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component._REF_HOOK_IMPORTS",
                source,
            })?;
        let lifecycle_hook_imports = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("_LIFECYCLE_HOOK_IMPORTS"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component._LIFECYCLE_HOOK_IMPORTS",
                source,
            })?;
        let component_app_wrap_base = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("Component"))
            .and_then(|c| c.getattr("_get_app_wrap_components"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.Component._get_app_wrap_components",
                source,
            })?;
        let parse_imports = py
            .import_bound("reflex_base.utils.imports")
            .and_then(|m| m.getattr("parse_imports"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.utils.imports.parse_imports",
                source,
            })?;
        let dict_builtin = py
            .import_bound("builtins")
            .and_then(|m| m.getattr("dict"))
            .map_err(|source| PyReadError::Attr {
                attr: "builtins.dict",
                source,
            })?;
        let component_get_imports_base = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("Component"))
            .and_then(|c| c.getattr("_get_imports"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.Component._get_imports",
                source,
            })?;
        let component_field_cls = py
            .import_bound("reflex_base.components.component")
            .and_then(|m| m.getattr("ComponentField"))
            .map_err(|source| PyReadError::Attr {
                attr: "reflex_base.components.component.ComponentField",
                source,
            })?;
        let breakpoints_mod = py
            .import_bound("reflex_base.breakpoints")
            .map_err(|source| PyReadError::Attr {
                attr: "import reflex_base.breakpoints",
                source,
            })?;
        let breakpoints_cls =
            breakpoints_mod
                .getattr("Breakpoints")
                .map_err(|source| PyReadError::Attr {
                    attr: "reflex_base.breakpoints.Breakpoints",
                    source,
                })?;
        let breakpoints_values =
            breakpoints_mod
                .getattr("breakpoints_values")
                .map_err(|source| PyReadError::Attr {
                    attr: "reflex_base.breakpoints.breakpoints_values",
                    source,
                })?;
        let rustvar_type = pyo3::types::PyType::new_bound::<reflex_vars::RustVar>(py).into_any();
        let rustvar_js_expr_desc =
            rustvar_type
                .getattr("_js_expr")
                .map_err(|source| PyReadError::Attr {
                    attr: "RustVar._js_expr descriptor",
                    source,
                })?;
        let rustvar_gavd_desc = rustvar_type
            .getattr("_get_all_var_data")
            .map_err(|source| PyReadError::Attr {
                attr: "RustVar._get_all_var_data descriptor",
                source,
            })?;
        Ok(Self {
            var_cls,
            literal_var_cls,
            format_library_name,
            format_as_emotion,
            component_get_style_base,
            component_exclude_props_base,
            component_render_base,
            events_imports,
            ref_hook_imports,
            lifecycle_hook_imports,
            component_app_wrap_base,
            parse_imports,
            dict_builtin,
            component_get_imports_base,
            component_field_cls,
            breakpoints_cls,
            breakpoints_values,
            rustvar_type,
            rustvar_js_expr_desc,
            rustvar_gavd_desc,
            harvest: RefCell::new(HarvestState::default()),
            memo_mode_cache: RefCell::new(HashMap::with_capacity(32)),
            var_data_dedup: RefCell::new(HashMap::with_capacity(32)),
            bun_imports: RefCell::new(None),
            imports_seen: RefCell::new(HashSet::with_capacity(64)),
            app_wraps: RefCell::new(None),
            app_wraps_seen: RefCell::new(HashSet::with_capacity(8)),
            attrs: InternedAttrs::new(py),
            method_cache: RefCell::new(HashMap::with_capacity(32)),
            class_cache: None,
            freeze_crossings_counter: None,
            freeze_trivial_skips_counter: None,
            direct_get_props_calls: None,
            direct_rename_props_reads: None,
            // A: lazy-init the module ref on first session caches
            // attach, so legacy `read_page` callers (no session)
            // skip this entirely.
            native_module: py
                .import_bound("reflex_compiler_rust._native")
                .ok()
                .map(|m| m.unbind().into()),
        })
    }

    /// Attach session-scoped caches to this PyRefs. Called by
    /// `compile_page_from_component_arena` so freeze can use the
    /// cross-call class metadata table.
    pub fn with_session_caches(
        mut self,
        class_cache: std::rc::Rc<RefCell<ClassMetadataCache>>,
        freeze_crossings: std::rc::Rc<Cell<u64>>,
        freeze_trivial_skips: std::rc::Rc<Cell<u64>>,
        direct_get_props_calls: std::rc::Rc<Cell<u64>>,
        direct_rename_props_reads: std::rc::Rc<Cell<u64>>,
    ) -> Self {
        self.class_cache = Some(class_cache);
        self.freeze_crossings_counter = Some(freeze_crossings);
        self.freeze_trivial_skips_counter = Some(freeze_trivial_skips);
        self.direct_get_props_calls = Some(direct_get_props_calls);
        self.direct_rename_props_reads = Some(direct_rename_props_reads);
        self
    }

    /// Bump the per-feature direct-from-Rust counter for B.
    #[inline]
    pub fn bump_direct_get_props(&self) {
        if let Some(c) = &self.direct_get_props_calls {
            c.set(c.get() + 1);
        }
    }
    #[inline]
    pub fn bump_direct_rename_props(&self) {
        if let Some(c) = &self.direct_rename_props_reads {
            c.set(c.get() + 1);
        }
    }

    /// Bump the boundary-crossings counter (A perf invariant).
    #[inline]
    pub fn bump_crossings(&self, n: u64) {
        if let Some(c) = &self.freeze_crossings_counter {
            c.set(c.get() + n);
        }
    }

    /// Bump the trivial-skip count (C invariant).
    #[inline]
    pub fn bump_trivial_skip(&self) {
        if let Some(c) = &self.freeze_trivial_skips_counter {
            c.set(c.get() + 1);
        }
    }
}

impl<'py> PyRefs<'py> {
    /// Look up `method_name` on `type(obj)` once per class. Returns
    /// the cached unbound method object. Caller uses ``call1((obj,))``
    /// to invoke. ~100-300 ns saved per call after first-class warm.
    ///
    /// `accessor` selects which slot of `ClassMethodHandles` to fill
    /// and read; the caller picks the slot at compile time.
    pub fn cached_method<F>(
        &self,
        obj: &Bound<'py, PyAny>,
        method_name: &Bound<'py, PyString>,
        accessor: F,
    ) -> Option<Py<PyAny>>
    where
        F: Fn(&mut ClassMethodHandles) -> &mut Option<Py<PyAny>>,
    {
        let py = obj.py();
        let ty = obj.get_type();
        let key = ty.as_ptr() as usize;
        // B: prefer the session-scoped class cache so method handles
        // survive across compiles. Falls back to per-call
        // ``method_cache`` when no session cache is attached (legacy
        // ``read_page`` path).
        if let Some(class_cache_rc) = &self.class_cache {
            let mut cache = class_cache_rc.borrow_mut();
            let meta = cache.entry(key).or_default();
            let slot = accessor(&mut meta.method_handles);
            if let Some(cached) = slot.as_ref() {
                return Some(cached.clone_ref(py));
            }
            let resolved = ty.getattr(method_name).ok()?.unbind();
            *slot = Some(resolved.clone_ref(py));
            return Some(resolved);
        }
        let mut cache = self.method_cache.borrow_mut();
        let entry = cache.entry(key).or_default();
        let slot = accessor(entry);
        if let Some(cached) = slot.as_ref() {
            return Some(cached.clone_ref(py));
        }
        let resolved = ty.getattr(method_name).ok()?.unbind();
        *slot = Some(resolved.clone_ref(py));
        Some(resolved)
    }

    /// `obj.method_name()` with per-class method-handle caching.
    /// Falls back to the slow `call_method0` path on cache miss.
    /// `accessor` picks which slot of `ClassMethodHandles` to use.
    pub fn call_cached0<F>(
        &self,
        obj: &Bound<'py, PyAny>,
        method_name: &Bound<'py, PyString>,
        accessor: F,
    ) -> PyResult<Bound<'py, PyAny>>
    where
        F: Fn(&mut ClassMethodHandles) -> &mut Option<Py<PyAny>>,
    {
        let py = obj.py();
        if let Some(unbound) = self.cached_method(obj, method_name, accessor) {
            return unbound.bind(py).call1((obj,));
        }
        obj.call_method0(method_name)
    }
}

// ---- Top-level Page entry ---------------------------------------------------

/// Read a page's root Component into a `reflex_ir::Page<'arena>`.
///
/// Mirrors `reflex.compiler.ir.bridge.page_to_ir`.
pub fn read_page<'arena, 'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    route: &str,
    title: Option<&str>,
    meta_tags: &[(String, String)],
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Page<'arena>, PyReadError> {
    timing::reset();
    let _total = TSpan::new(TF::ReadPageTotal);

    // Reset the harvest accumulator so multiple `read_page` calls
    // sharing a `PyRefs` don't leak prior state into this page.
    *refs.harvest.borrow_mut() = HarvestState::default();

    let root_ir = read_component(py, root, arena, refs)?;
    let root_alloc: &Component<'arena> = arena.alloc(root_ir);

    let meta_arr: Vec<Meta<'arena>> = meta_tags
        .iter()
        .map(|(name, content)| Meta {
            name: intern(name),
            content: arena.alloc_str(content),
        })
        .collect();
    let meta_slice = arena.alloc_slice_fill_iter(meta_arr.into_iter());

    let route_str: &str = arena.alloc_str(route);
    let title_str: Option<&str> = title.map(|s| &*arena.alloc_str(s));

    // Drain the harvests collected during the single walk above.
    let harvest = refs.harvest.borrow();
    let component_imports = arena.alloc_slice_fill_iter(harvest.component_imports.iter().copied());
    let state_bindings = arena.alloc_slice_fill_iter(harvest.state_bindings.iter().copied());
    drop(harvest);

    Ok(Page {
        schema_version: SCHEMA_VERSION,
        route: route_str,
        root: root_alloc,
        title: title_str,
        meta: meta_slice,
        source_files: arena.alloc_slice_fill_iter(std::iter::empty::<PyFileId>()),
        component_imports,
        state_bindings,
        // Refs are carried by per-node hooks; no page-level ref flag.
        needs_ref: false,
    })
}

// ---- Component dispatch -----------------------------------------------------

fn read_component<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    timing::incr(TC::Node);
    let cls_name = {
        let _s = TSpan::new(TF::ClassName);
        class_name(component)?
    };
    match cls_name.as_str() {
        "Bare" => read_bare(py, component, arena, refs),
        "Fragment" => read_fragment(py, component, arena, refs),
        "Cond" => read_cond(py, component, arena, refs),
        "Foreach" => read_foreach(py, component, arena, refs),
        "Match" => read_match(py, component, arena, refs),
        _ => read_element(py, component, arena, refs),
    }
}

fn read_bare<'arena, 'py>(
    _py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    let contents = getattr(component, "contents")?;
    if contents.is_none() {
        return Ok(Component::Text {
            value: arena.alloc_str(""),
            id: NodeId::default(),
            source_loc: SourceLoc::SYNTHETIC,
        });
    }
    let is_var = isinstance(&contents, &refs.var_cls, "Bare.contents")?;
    if is_var {
        let js_expr = read_attr_str(&contents, "_js_expr", "Var._js_expr")?;
        if let Some(decoded) = decode_js_string_literal(&js_expr) {
            return Ok(Component::Text {
                value: arena.alloc_str(&decoded),
                id: NodeId::default(),
                source_loc: SourceLoc::SYNTHETIC,
            });
        }
        // Var-as-expression: emit `Component::Expr` with the JS expression
        // and its merged VarData. Codegen renders this inline.
        refs.harvest.borrow_mut().add_state_idents_in(&js_expr);
        let var_data = read_var_data(&contents, arena, refs)?;
        let value = Value::JsExpr {
            expr: arena.alloc_str(&js_expr),
            var_data,
        };
        return Ok(Component::Expr {
            value,
            id: NodeId::default(),
            source_loc: SourceLoc::SYNTHETIC,
        });
    }
    // Non-Var contents: stringify via Python's `str(...)`.
    let text = py_str(&contents)?;
    Ok(Component::Text {
        value: arena.alloc_str(&text),
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

fn read_fragment<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    let children = read_children(py, component, arena, refs)?;
    Ok(Component::Fragment {
        children,
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

fn read_cond<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    let cond_obj = getattr(component, "cond")?;
    let test = read_value(py, &cond_obj, arena, refs)?;

    let children_obj = getattr(component, "children")?;
    let children: Bound<'_, PyList> =
        children_obj
            .downcast_into()
            .map_err(|e| PyReadError::TypeMismatch {
                attr: "Cond.children",
                expected: "list",
                got: e.to_string(),
            })?;
    let mut iter = children.iter();
    let then_obj = iter.next();
    let else_obj = iter.next();

    let then_ir = match then_obj {
        Some(t) => read_component(py, &t, arena, refs)?,
        None => Component::Text {
            value: arena.alloc_str(""),
            id: NodeId::default(),
            source_loc: SourceLoc::SYNTHETIC,
        },
    };
    let then_alloc: &Component<'arena> = arena.alloc(then_ir);

    let else_alloc: Option<&Component<'arena>> = match else_obj {
        Some(e) => {
            let ir = read_component(py, &e, arena, refs)?;
            Some(arena.alloc(ir))
        }
        None => None,
    };

    Ok(Component::Cond {
        test,
        then: then_alloc,
        else_: else_alloc,
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

fn read_foreach<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    // Delegate to `_render()` so the iter-var arg is properly typed —
    // matches the bridge.py rationale (foreach bodies do `item["key"]`
    // etc. and need `ArrayCastedVar`/`ObjectVar`-shaped args).
    let iter_tag = component
        .call_method0("_render")
        .map_err(|source| PyReadError::Attr {
            attr: "Foreach._render()",
            source,
        })?;
    let body_component = iter_tag
        .call_method0("render_component")
        .map_err(|source| PyReadError::Attr {
            attr: "IterTag.render_component()",
            source,
        })?;
    let body_ir = read_component(py, &body_component, arena, refs)?;
    let body_alloc: &Component<'arena> = arena.alloc(body_ir);

    let iterable = getattr(component, "iterable")?;
    let iter_val = read_value(py, &iterable, arena, refs)?;
    Ok(Component::Foreach {
        iter: iter_val,
        body: body_alloc,
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

fn read_match<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    let cond_obj = getattr(component, "cond")?;
    let test = read_value(py, &cond_obj, arena, refs)?;

    let match_cases_obj = match component.getattr("match_cases") {
        Ok(v) if !v.is_none() => v,
        _ => {
            // No cases — emit an empty Match with no default.
            return Ok(Component::Match {
                value: test,
                arms: arena.alloc_slice_fill_iter(std::iter::empty::<MatchArm<'arena>>()),
                default: None,
                id: NodeId::default(),
                source_loc: SourceLoc::SYNTHETIC,
            });
        }
    };
    let match_cases: Bound<'_, PyList> =
        match_cases_obj
            .downcast_into()
            .map_err(|e| PyReadError::TypeMismatch {
                attr: "Match.match_cases",
                expected: "list",
                got: e.to_string(),
            })?;

    // Match case entries can arrive as either a list or a tuple
    // (`[case_a, case_b, ..., body_component]`); use the generic
    // sequence protocol so both work without a downcast dance.
    let mut arms_vec: Vec<MatchArm<'arena>> = Vec::with_capacity(match_cases.len());
    for case_entry in match_cases.iter() {
        let entries: Vec<Bound<'_, PyAny>> = case_entry
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
        let body_obj = &entries[entries.len() - 1];
        let body_ir = read_component(py, body_obj, arena, refs)?;
        let body_alloc: &Component<'arena> = arena.alloc(body_ir);
        for case_val_obj in &entries[..entries.len() - 1] {
            let case = read_value(py, case_val_obj, arena, refs)?;
            arms_vec.push(MatchArm {
                case,
                body: body_alloc,
            });
        }
    }

    let default_obj = component.getattr("default").ok().filter(|v| !v.is_none());
    let default: Option<&Component<'arena>> = match default_obj {
        Some(d) => {
            let ir = read_component(py, &d, arena, refs)?;
            Some(arena.alloc(ir))
        }
        None => None,
    };

    Ok(Component::Match {
        value: test,
        arms: arena.alloc_slice_fill_iter(arms_vec.into_iter()),
        default,
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

fn read_element<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Component<'arena>, PyReadError> {
    timing::incr(TC::Element);
    let tag_sym = {
        let _s = TSpan::new(TF::ResolveTag);
        resolve_tag_symbol(component)?
    };

    // Harvest the component's module/spec for the page-level
    // `import {...} from "<module>";` lines. Inlined from
    // `collect_component_imports` so the bridge doesn't have to walk the
    // tree a second time after IR construction.
    {
        let _s = TSpan::new(TF::ImportAlias);
        if let Some(pair) = import_alias_for(component, refs)? {
            let _h = TSpan::new(TF::HarvestRegister);
            refs.harvest.borrow_mut().add_component_import(pair);
        }
    }

    // No tag → emit as Fragment around children (matches bridge.py).
    if tag_sym == Symbol::EMPTY {
        let children = read_children(py, component, arena, refs)?;
        return Ok(Component::Fragment {
            children,
            id: NodeId::default(),
            source_loc: SourceLoc::SYNTHETIC,
        });
    }

    // No spans around read_props / read_children / read_event_handlers —
    // they recurse (props value → nested vars/components, children →
    // read_component, event_handlers → event_handler_to_js → read_var_data)
    // so wrapping them would double-count nested work in their own
    // accumulators. The leaf spans inside (`ReadVarData`, `ResolveTag`,
    // `ImportAlias`, etc.) report self-time accurately; everything not
    // covered shows up in the `(unaccounted)` line of the reporter.
    let props = read_props(py, component, arena, refs)?;
    let children = read_children(py, component, arena, refs)?;
    let events = read_event_handlers(py, component, arena, refs)?;
    let hooks: &[Hook<'arena>] = arena.alloc_slice_fill_iter(std::iter::empty::<Hook<'arena>>());
    Ok(Component::Element {
        tag: tag_sym,
        props,
        children,
        event_handlers: events,
        hooks,
        id: NodeId::default(),
        source_loc: SourceLoc::SYNTHETIC,
    })
}

// ---- Props, children, events ------------------------------------------------

fn read_children<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<&'arena [Component<'arena>], PyReadError> {
    let (children_obj, iter) = {
        let _s = TSpan::new(TF::ChildrenAttr);
        let children_obj = match component.getattr("children") {
            Ok(v) if !v.is_none() => v,
            _ => return Ok(arena.alloc_slice_fill_iter(std::iter::empty::<Component<'arena>>())),
        };
        let iter = children_obj.iter().map_err(|source| PyReadError::Attr {
            attr: "iter(component.children)",
            source,
        })?;
        (children_obj, iter)
    };
    let _ = children_obj;
    let mut out: Vec<Component<'arena>> = Vec::new();
    for item in iter {
        let child = item.map_err(|source| PyReadError::Attr {
            attr: "component.children[i]",
            source,
        })?;
        out.push(read_component(py, &child, arena, refs)?);
    }
    Ok(arena.alloc_slice_fill_iter(out.into_iter()))
}

fn read_props<'arena, 'py>(
    py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<&'arena [(Symbol, Value<'arena>)], PyReadError> {
    let mut props: Vec<(Symbol, Value<'arena>)> = Vec::new();

    // Component fields (the dataclass props), in Component.get_props() order.
    let prop_names_obj = {
        let _s = TSpan::new(TF::GetPropsCall);
        component
            .call_method0("get_props")
            .map_err(|source| PyReadError::Attr {
                attr: "Component.get_props()",
                source,
            })?
    };
    let prop_names_iter = prop_names_obj.iter().map_err(|source| PyReadError::Attr {
        attr: "iter(get_props())",
        source,
    })?;
    for name_res in prop_names_iter {
        timing::incr(TC::Prop);
        let name_obj = name_res.map_err(|source| PyReadError::Attr {
            attr: "get_props()[i]",
            source,
        })?;
        let raw: String = py_str(&name_obj)?;
        let attr_name = raw.strip_suffix('_').unwrap_or(&raw).to_owned();
        let value_obj = {
            let _s = TSpan::new(TF::PropValueGetattr);
            match component.getattr(raw.as_str()) {
                Ok(v) => v,
                Err(_) => continue,
            }
        };
        if value_obj.is_none() {
            continue;
        }
        let value = read_value(py, &value_obj, arena, refs)?;
        props.push((intern(&attr_name), value));
    }

    // Identity props the legacy renderer always splices.
    for name in ["key", "id", "class_name"] {
        let v = {
            let _s = TSpan::new(TF::PropValueGetattr);
            match component.getattr(name) {
                Ok(v) if !v.is_none() => v,
                _ => continue,
            }
        };
        let value = read_value(py, &v, arena, refs)?;
        props.push((intern(name), value));
    }

    // custom_attrs: any extra string-keyed attributes.
    if let Ok(custom) = component.getattr("custom_attrs") {
        if !custom.is_none() {
            if let Ok(mapping) = custom.downcast::<PyMapping>() {
                let keys = mapping.keys().map_err(|source| PyReadError::Attr {
                    attr: "custom_attrs.keys()",
                    source,
                })?;
                for key_res in keys.iter().map_err(|source| PyReadError::Attr {
                    attr: "iter(custom_attrs.keys())",
                    source,
                })? {
                    let key = key_res.map_err(|source| PyReadError::Attr {
                        attr: "custom_attrs.keys()[i]",
                        source,
                    })?;
                    let name: String = py_str(&key)?;
                    let val = mapping.get_item(&key).map_err(|source| PyReadError::Attr {
                        attr: "custom_attrs[k]",
                        source,
                    })?;
                    let value = read_value(py, &val, arena, refs)?;
                    props.push((intern(&name), value));
                }
            }
        }
    }

    Ok(arena.alloc_slice_fill_iter(props.into_iter()))
}

fn read_event_handlers<'arena, 'py>(
    _py: Python<'py>,
    component: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<&'arena [EventHandler<'arena>], PyReadError> {
    let triggers = {
        let _s = TSpan::new(TF::EventTriggersAttr);
        let triggers_obj = match component.getattr("event_triggers") {
            Ok(v) if !v.is_none() => v,
            _ => return Ok(arena.alloc_slice_fill_iter(std::iter::empty::<EventHandler<'arena>>())),
        };
        let triggers: Bound<'_, PyDict> =
            triggers_obj
                .downcast_into()
                .map_err(|e| PyReadError::TypeMismatch {
                    attr: "Component.event_triggers",
                    expected: "dict",
                    got: e.to_string(),
                })?;
        triggers
    };

    let mut out: Vec<EventHandler<'arena>> = Vec::with_capacity(triggers.len());
    for (trigger_obj, handler_obj) in triggers.iter() {
        timing::incr(TC::EventHandler);
        let trigger_name: String = py_str(&trigger_obj)?;
        if trigger_name == "on_mount" || trigger_name == "on_unmount" {
            // Side-effect triggers handled outside JSX — match bridge.py.
            continue;
        }
        let (expr, var_data) = event_handler_to_js(&handler_obj, arena, refs)?;
        out.push(EventHandler {
            trigger: intern(&trigger_name),
            expr: arena.alloc_str(&expr),
            var_data,
        });
    }
    Ok(arena.alloc_slice_fill_iter(out.into_iter()))
}

fn event_handler_to_js<'arena>(
    handler: &Bound<'_, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'_>,
) -> Result<(String, VarData<'arena>), PyReadError> {
    if isinstance(handler, &refs.var_cls, "event handler")? {
        let expr = read_attr_str(handler, "_js_expr", "Var._js_expr")?;
        refs.harvest.borrow_mut().add_state_idents_in(&expr);
        let var_data = read_var_data(handler, arena, refs)?;
        return Ok((expr, var_data));
    }
    // Wrap via `LiteralVar.create(handler)` so EventChain / EventSpec /
    // dict / list values get a proper JS expression + VarData.
    let wrapped = refs
        .literal_var_cls
        .call_method1("create", (handler,))
        .map_err(|source| PyReadError::Attr {
            attr: "LiteralVar.create(event handler)",
            source,
        })?;
    if isinstance(&wrapped, &refs.var_cls, "LiteralVar.create result")? {
        let expr = read_attr_str(&wrapped, "_js_expr", "Var._js_expr")?;
        refs.harvest.borrow_mut().add_state_idents_in(&expr);
        let var_data = read_var_data(&wrapped, arena, refs)?;
        Ok((expr, var_data))
    } else {
        Ok((py_str(&wrapped)?, VarData::EMPTY))
    }
}

// ---- Value (Var vs literal) -------------------------------------------------

fn read_value<'arena, 'py>(
    _py: Python<'py>,
    value: &Bound<'py, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'py>,
) -> Result<Value<'arena>, PyReadError> {
    let is_var = {
        let _s = TSpan::new(TF::IsInstanceVar);
        isinstance(value, &refs.var_cls, "prop value")?
    };
    if is_var {
        timing::incr(TC::Var);
        let expr = {
            let _s = TSpan::new(TF::VarJsExprAttr);
            read_attr_str(value, "_js_expr", "Var._js_expr")?
        };
        refs.harvest.borrow_mut().add_state_idents_in(&expr);
        let var_data = read_var_data(value, arena, refs)?;
        return Ok(Value::JsExpr {
            expr: arena.alloc_str(&expr),
            var_data,
        });
    }
    let _s_lit = TSpan::new(TF::ValueLiteralDispatch);
    if value.is_none() {
        return Ok(Value::Literal(Literal::Null));
    }
    if let Ok(b) = value.downcast::<PyBool>() {
        return Ok(Value::Literal(Literal::Bool(b.is_true())));
    }
    if let Ok(i) = value.downcast::<PyInt>() {
        let n: i64 = i.extract().map_err(|source| PyReadError::Attr {
            attr: "int.extract()",
            source,
        })?;
        return Ok(Value::Literal(Literal::Int(n)));
    }
    if let Ok(f) = value.downcast::<PyFloat>() {
        let v: f64 = f.extract().map_err(|source| PyReadError::Attr {
            attr: "float.extract()",
            source,
        })?;
        return Ok(Value::Literal(Literal::Float(v)));
    }
    if let Ok(s) = value.downcast::<PyString>() {
        let raw = s.to_str().map_err(|source| PyReadError::Attr {
            attr: "PyString::to_str",
            source,
        })?;
        return Ok(Value::Literal(Literal::Str(arena.alloc_str(raw))));
    }
    // Complex Python values (EventChain, lists, dicts, …): wrap via
    // `LiteralVar.create` and read as a Var. Matches bridge.var_to_value.
    let wrapped = refs
        .literal_var_cls
        .call_method1("create", (value,))
        .map_err(|source| PyReadError::Attr {
            attr: "LiteralVar.create(prop value)",
            source,
        })?;
    if isinstance(&wrapped, &refs.var_cls, "LiteralVar.create result")? {
        let expr = read_attr_str(&wrapped, "_js_expr", "Var._js_expr")?;
        let var_data = read_var_data(&wrapped, arena, refs)?;
        return Ok(Value::JsExpr {
            expr: arena.alloc_str(&expr),
            var_data,
        });
    }
    // Last-ditch: stringify.
    Ok(Value::JsExpr {
        expr: arena.alloc_str(&py_str(&wrapped)?),
        var_data: VarData::EMPTY,
    })
}

// ---- VarData ----------------------------------------------------------------

fn read_var_data<'arena>(
    var: &Bound<'_, PyAny>,
    arena: &'arena Arena,
    refs: &PyRefs<'_>,
) -> Result<VarData<'arena>, PyReadError> {
    let _s = TSpan::new(TF::ReadVarData);
    let vd_obj = match var.call_method0("_get_all_var_data") {
        Ok(v) if !v.is_none() => v,
        _ => match var.getattr("_var_data") {
            Ok(v) if !v.is_none() => v,
            _ => return Ok(VarData::EMPTY),
        },
    };

    // hooks: list[str]
    let hooks: &'arena [&'arena str] = match vd_obj.getattr("hooks") {
        Ok(v) if !v.is_none() => {
            let mut out: Vec<&'arena str> = Vec::new();
            for item in v.iter().map_err(|source| PyReadError::Attr {
                attr: "iter(VarData.hooks)",
                source,
            })? {
                let s = item.map_err(|source| PyReadError::Attr {
                    attr: "VarData.hooks[i]",
                    source,
                })?;
                let raw = py_str(&s)?;
                out.push(arena.alloc_str(&raw));
            }
            arena.alloc_slice_fill_iter(out.into_iter())
        }
        _ => arena.alloc_slice_fill_iter(std::iter::empty::<&str>()),
    };

    // imports: ParsedImportTuple or dict[str, list[ImportVar]]
    let imports = read_var_data_imports(&vd_obj, refs)?;
    let imports_slice = arena.alloc_slice_fill_iter(imports.into_iter());

    // state: Optional[str]
    let state = match vd_obj.getattr("state") {
        Ok(v) if !v.is_none() => Some(intern(&py_str(&v)?)),
        _ => None,
    };

    // deps: list[Var | str]
    let deps: &'arena [Symbol] = match vd_obj.getattr("deps") {
        Ok(v) if !v.is_none() => {
            let mut out: Vec<Symbol> = Vec::new();
            for item in v.iter().map_err(|source| PyReadError::Attr {
                attr: "iter(VarData.deps)",
                source,
            })? {
                let d = item.map_err(|source| PyReadError::Attr {
                    attr: "VarData.deps[i]",
                    source,
                })?;
                out.push(intern(&py_str(&d)?));
            }
            arena.alloc_slice_fill_iter(out.into_iter())
        }
        _ => arena.alloc_slice_fill_iter(std::iter::empty::<Symbol>()),
    };

    // position: Optional[int | enum-with-value]
    let position = match vd_obj.getattr("position") {
        Ok(v) if !v.is_none() => {
            let p = if let Ok(pi) = v.extract::<u8>() {
                Some(pi)
            } else if let Ok(value_attr) = v.getattr("value") {
                value_attr.extract::<u8>().ok()
            } else {
                None
            };
            p
        }
        _ => None,
    };

    // components: list[str]
    let components: &'arena [Symbol] = match vd_obj.getattr("components") {
        Ok(v) if !v.is_none() => {
            let mut out: Vec<Symbol> = Vec::new();
            for item in v.iter().map_err(|source| PyReadError::Attr {
                attr: "iter(VarData.components)",
                source,
            })? {
                let c = item.map_err(|source| PyReadError::Attr {
                    attr: "VarData.components[i]",
                    source,
                })?;
                out.push(intern(&py_str(&c)?));
            }
            arena.alloc_slice_fill_iter(out.into_iter())
        }
        _ => arena.alloc_slice_fill_iter(std::iter::empty::<Symbol>()),
    };

    Ok(VarData {
        hooks,
        imports: imports_slice,
        state,
        deps,
        position,
        components,
    })
}

fn read_var_data_imports(
    vd: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<Vec<(Symbol, Symbol)>, PyReadError> {
    let raw = match vd.getattr("imports") {
        Ok(v) if !v.is_none() => v,
        _ => return Ok(Vec::new()),
    };
    // `ParsedImportTuple = tuple[tuple[str, tuple[ImportVar, ...]], ...]`,
    // or `dict[str, list[ImportVar]]`. Iterate either as (module, entries).
    let mut iter_pairs: Vec<(Bound<'_, PyAny>, Bound<'_, PyAny>)> = Vec::new();
    if let Ok(d) = raw.downcast::<PyDict>() {
        for (k, v) in d.iter() {
            iter_pairs.push((k, v));
        }
    } else {
        for pair in raw.iter().map_err(|source| PyReadError::Attr {
            attr: "iter(VarData.imports)",
            source,
        })? {
            let p = pair.map_err(|source| PyReadError::Attr {
                attr: "VarData.imports[i]",
                source,
            })?;
            let t: Bound<'_, PyTuple> =
                p.downcast_into().map_err(|e| PyReadError::TypeMismatch {
                    attr: "VarData.imports[i]",
                    expected: "tuple",
                    got: e.to_string(),
                })?;
            if t.len() != 2 {
                continue;
            }
            iter_pairs.push((
                t.get_item(0).map_err(|source| PyReadError::Attr {
                    attr: "VarData.imports[i][0]",
                    source,
                })?,
                t.get_item(1).map_err(|source| PyReadError::Attr {
                    attr: "VarData.imports[i][1]",
                    source,
                })?,
            ));
        }
    }

    let mut out: Vec<(Symbol, Symbol)> = Vec::new();
    for (module_obj, entries) in iter_pairs {
        let module_raw = py_str(&module_obj)?;
        let module = format_library_name(refs, &module_raw)?;
        if module.is_empty() {
            // Side-effect import; bridge.py skips these for the in-braces list.
            continue;
        }
        for entry in entries.iter().map_err(|source| PyReadError::Attr {
            attr: "iter(imports[module])",
            source,
        })? {
            let e = entry.map_err(|source| PyReadError::Attr {
                attr: "imports[module][i]",
                source,
            })?;
            let tag = read_import_var_tag(&e)?;
            if tag.is_empty() {
                continue;
            }
            let tag_root: String = tag.split('.').next().unwrap_or("").to_owned();
            if !is_js_identifier(&tag_root) {
                continue;
            }
            let module_sym = intern(&module);
            let tag_sym = intern(&tag_root);
            out.push((module_sym, tag_sym));
            // Register at the page level too, matching the old
            // `vardata_import_pairs` walk. Filter out the React runtime
            // names that always come from the baseline imports.
            if !(module == "react"
                && matches!(tag_root.as_str(), "Fragment" | "useContext" | "useRef"))
            {
                refs.harvest
                    .borrow_mut()
                    .add_component_import((module_sym, tag_sym));
            }
        }
    }
    Ok(out)
}

fn read_import_var_tag(entry: &Bound<'_, PyAny>) -> Result<String, PyReadError> {
    let tag = entry.getattr("tag").ok().filter(|v| !v.is_none());
    if let Some(t) = tag {
        if let Ok(s) = py_str(&t) {
            if !s.is_empty() {
                return Ok(s);
            }
        }
    }
    let name = entry.getattr("name").ok().filter(|v| !v.is_none());
    if let Some(n) = name {
        if let Ok(s) = py_str(&n) {
            return Ok(s);
        }
    }
    Ok(String::new())
}

// ---- Page-level harvest walks ----------------------------------------------
//
// Kept for reference / future parity testing. These were the three
// post-IR-build walks `read_page` used to run; they're superseded by
// the inline harvest registrations in `read_element`, `read_var_data_imports`,
// `read_value`, and `read_bare` above.

#[allow(dead_code)]
fn collect_component_imports(
    py: Python<'_>,
    root: &Bound<'_, PyAny>,
    arena: &Arena,
    refs: &PyRefs<'_>,
) -> Result<Vec<(Symbol, Symbol)>, PyReadError> {
    let mut seen: HashSet<(Symbol, Symbol)> = HashSet::new();
    let mut out: Vec<(Symbol, Symbol)> = Vec::new();
    let mut push = |pair: (Symbol, Symbol)| {
        if seen.insert(pair) {
            out.push(pair);
        }
    };

    walk_components(root, &mut |comp| {
        if let Some(pair) = import_alias_for(comp, refs)? {
            push(pair);
        }
        Ok(())
    })?;

    // VarData imports — second pass over all Vars in the tree.
    walk_values(root, refs, &mut |var| {
        let pairs = vardata_import_pairs(var, refs)?;
        for p in pairs {
            push(p);
        }
        Ok(())
    })?;
    let _ = (py, arena); // unused, kept for future GIL handling
    Ok(out)
}

fn import_alias_for(
    component: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<Option<(Symbol, Symbol)>, PyReadError> {
    let inst_dict = instance_dict(component, refs);
    let library = match read_field(
        component,
        inst_dict.as_ref(),
        "library",
        &refs.attrs.library,
        refs,
    ) {
        Some(v) if !v.is_none() => v,
        _ => return Ok(None),
    };
    let library_raw = py_str(&library)?;
    let tag = read_field(component, inst_dict.as_ref(), "tag", &refs.attrs.tag, refs)
        .filter(|v| !v.is_none());
    let alias = read_field(
        component,
        inst_dict.as_ref(),
        "alias",
        &refs.attrs.alias,
        refs,
    )
    .filter(|v| !v.is_none());
    if tag.is_none() && alias.is_none() {
        return Ok(None);
    }

    let module = format_library_name(refs, &library_raw)?;
    let tag_root = tag
        .as_ref()
        .and_then(|t| py_str(t).ok())
        .map(|s| s.split('.').next().unwrap_or("").to_owned());
    let alias_root = alias
        .as_ref()
        .and_then(|a| py_str(a).ok())
        .map(|s| s.split('.').next().unwrap_or("").to_owned());

    if module == "react"
        && matches!(
            tag_root.as_deref(),
            Some("Fragment") | Some("useContext") | Some("useRef")
        )
    {
        return Ok(None);
    }

    let spec = match (&tag_root, &alias_root) {
        (Some(t), Some(a)) if a != t && !a.is_empty() => format!("{t} as {a}"),
        (Some(t), _) if !t.is_empty() => t.clone(),
        (_, Some(a)) if !a.is_empty() => a.clone(),
        _ => return Ok(None),
    };

    Ok(Some((intern(&module), intern(&spec))))
}

#[allow(dead_code)]
fn vardata_import_pairs(
    var: &Bound<'_, PyAny>,
    refs: &PyRefs<'_>,
) -> Result<Vec<(Symbol, Symbol)>, PyReadError> {
    let vd = match var.call_method0("_get_all_var_data") {
        Ok(v) if !v.is_none() => v,
        _ => return Ok(Vec::new()),
    };
    let raw = match vd.getattr("imports") {
        Ok(v) if !v.is_none() => v,
        _ => return Ok(Vec::new()),
    };
    let mut pairs: Vec<(Bound<'_, PyAny>, Bound<'_, PyAny>)> = Vec::new();
    if let Ok(d) = raw.downcast::<PyDict>() {
        for (k, v) in d.iter() {
            pairs.push((k, v));
        }
    } else {
        for item in raw.iter().map_err(|source| PyReadError::Attr {
            attr: "iter(VarData.imports)",
            source,
        })? {
            let p = item.map_err(|source| PyReadError::Attr {
                attr: "VarData.imports[i]",
                source,
            })?;
            let t: Bound<'_, PyTuple> =
                p.downcast_into().map_err(|e| PyReadError::TypeMismatch {
                    attr: "VarData.imports tuple",
                    expected: "tuple",
                    got: e.to_string(),
                })?;
            if t.len() != 2 {
                continue;
            }
            pairs.push((
                t.get_item(0).map_err(|source| PyReadError::Attr {
                    attr: "VarData.imports[i][0]",
                    source,
                })?,
                t.get_item(1).map_err(|source| PyReadError::Attr {
                    attr: "VarData.imports[i][1]",
                    source,
                })?,
            ));
        }
    }
    let mut out: Vec<(Symbol, Symbol)> = Vec::new();
    for (module_obj, entries) in pairs {
        let module_raw = py_str(&module_obj)?;
        let module = format_library_name(refs, &module_raw)?;
        if module.is_empty() {
            continue;
        }
        for entry in entries.iter().map_err(|source| PyReadError::Attr {
            attr: "iter(imports[module])",
            source,
        })? {
            let e = entry.map_err(|source| PyReadError::Attr {
                attr: "imports[module][i]",
                source,
            })?;
            let tag = read_import_var_tag(&e)?;
            if tag.is_empty() {
                continue;
            }
            let root: String = tag.split('.').next().unwrap_or("").to_owned();
            if !is_js_identifier(&root) {
                continue;
            }
            if module == "react" && matches!(root.as_str(), "Fragment" | "useContext" | "useRef") {
                continue;
            }
            out.push((intern(&module), intern(&root)));
        }
    }
    Ok(out)
}

#[allow(dead_code)]
fn collect_state_bindings(
    _py: Python<'_>,
    root: &Bound<'_, PyAny>,
    _arena: &Arena,
    refs: &PyRefs<'_>,
) -> Result<Vec<Symbol>, PyReadError> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<Symbol> = Vec::new();
    walk_values(root, refs, &mut |var| {
        if let Ok(expr) = read_attr_str(var, "_js_expr", "Var._js_expr") {
            for m in find_state_idents(&expr) {
                if seen.insert(m.to_owned()) {
                    out.push(intern(&m));
                }
            }
        }
        Ok(())
    })?;
    Ok(out)
}

/// Find `reflex___state____state__<name>_state` identifiers inside `expr`.
/// Hand-rolled (avoids pulling regex into the crate); the bridge.py regex
/// is `\breflex___state____state__[A-Za-z0-9_]+_state\b`.
fn find_state_idents(expr: &str) -> Vec<String> {
    const PREFIX: &str = "reflex___state____state__";
    const SUFFIX: &str = "_state";
    let mut out: Vec<String> = Vec::new();
    let bytes = expr.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i..].starts_with(PREFIX.as_bytes()) {
            // Boundary check on the left.
            if i > 0 {
                let prev = bytes[i - 1];
                if prev.is_ascii_alphanumeric() || prev == b'_' {
                    i += 1;
                    continue;
                }
            }
            let body_start = i + PREFIX.len();
            let mut j = body_start;
            while j < bytes.len() {
                let c = bytes[j];
                if c.is_ascii_alphanumeric() || c == b'_' {
                    j += 1;
                } else {
                    break;
                }
            }
            // Body must end with `_state` and right boundary must be non-word.
            if j > body_start && bytes[..j].ends_with(SUFFIX.as_bytes()) {
                let right_ok =
                    j == bytes.len() || !(bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_');
                if right_ok {
                    out.push(String::from_utf8_lossy(&bytes[i..j]).into_owned());
                    i = j;
                    continue;
                }
            }
            i = body_start;
        } else {
            i += 1;
        }
    }
    out
}

// ---- Tree iteration ---------------------------------------------------------

#[allow(dead_code)]
fn walk_components<F>(root: &Bound<'_, PyAny>, f: &mut F) -> Result<(), PyReadError>
where
    F: FnMut(&Bound<'_, PyAny>) -> Result<(), PyReadError>,
{
    f(root)?;
    if let Ok(children) = root.getattr("children") {
        if !children.is_none() {
            if let Ok(iter) = children.iter() {
                for c in iter {
                    let child = c.map_err(|source| PyReadError::Attr {
                        attr: "iter(children)",
                        source,
                    })?;
                    walk_components(&child, f)?;
                }
            }
        }
    }
    Ok(())
}

/// Yield every Var-typed value reachable from `root` (props, identity
/// props, event handlers, Bare contents). Matches bridge._walk_values.
#[allow(dead_code)]
fn walk_values<F>(root: &Bound<'_, PyAny>, refs: &PyRefs<'_>, f: &mut F) -> Result<(), PyReadError>
where
    F: FnMut(&Bound<'_, PyAny>) -> Result<(), PyReadError>,
{
    walk_components(root, &mut |comp| {
        if let Ok(prop_names) = comp.call_method0("get_props") {
            if let Ok(iter) = prop_names.iter() {
                for name_res in iter {
                    let name_obj = name_res.map_err(|source| PyReadError::Attr {
                        attr: "iter(get_props())",
                        source,
                    })?;
                    let raw: String = py_str(&name_obj)?;
                    let attr_name = raw.strip_suffix('_').unwrap_or(&raw);
                    if let Ok(v) = comp.getattr(attr_name) {
                        if isinstance(&v, &refs.var_cls, "prop value")? {
                            f(&v)?;
                        }
                    }
                }
            }
        }
        for name in ["key", "id", "class_name"] {
            if let Ok(v) = comp.getattr(name) {
                if !v.is_none() && isinstance(&v, &refs.var_cls, "identity prop")? {
                    f(&v)?;
                }
            }
        }
        if let Ok(triggers) = comp.getattr("event_triggers") {
            if !triggers.is_none() {
                if let Ok(d) = triggers.downcast::<PyDict>() {
                    for (_trigger, handler) in d.iter() {
                        if isinstance(&handler, &refs.var_cls, "event handler")? {
                            f(&handler)?;
                        } else if let Ok(wrapped) =
                            refs.literal_var_cls.call_method1("create", (&handler,))
                        {
                            if isinstance(&wrapped, &refs.var_cls, "LiteralVar.create result")? {
                                f(&wrapped)?;
                            }
                        }
                    }
                }
            }
        }
        if let Ok(contents) = comp.getattr("contents") {
            if !contents.is_none() && isinstance(&contents, &refs.var_cls, "Bare.contents")? {
                f(&contents)?;
            }
        }
        Ok(())
    })
}

// ---- PyO3 helpers -----------------------------------------------------------

fn getattr<'py>(
    obj: &Bound<'py, PyAny>,
    attr: &'static str,
) -> Result<Bound<'py, PyAny>, PyReadError> {
    obj.getattr(attr)
        .map_err(|source| PyReadError::Attr { attr, source })
}

fn read_attr_str(
    obj: &Bound<'_, PyAny>,
    attr: &str,
    attr_static: &'static str,
) -> Result<String, PyReadError> {
    let v = obj.getattr(attr).map_err(|source| PyReadError::Attr {
        attr: attr_static,
        source,
    })?;
    py_str(&v)
}

fn isinstance(
    obj: &Bound<'_, PyAny>,
    cls: &Bound<'_, PyAny>,
    attr_static: &'static str,
) -> Result<bool, PyReadError> {
    obj.is_instance(cls).map_err(|source| PyReadError::Attr {
        attr: attr_static,
        source,
    })
}

pub(crate) fn py_str(obj: &Bound<'_, PyAny>) -> Result<String, PyReadError> {
    let s: Bound<'_, PyString> = obj.str().map_err(|source| PyReadError::Attr {
        attr: "str(value)",
        source,
    })?;
    s.to_str()
        .map(|v| v.to_owned())
        .map_err(|source| PyReadError::Attr {
            attr: "PyString::to_str",
            source,
        })
}

pub(crate) fn class_name(component: &Bound<'_, PyAny>) -> Result<String, PyReadError> {
    let ty = component
        .get_type()
        .name()
        .map_err(|source| PyReadError::Attr {
            attr: "__class__.__name__",
            source,
        })?;
    Ok(ty.to_string())
}

fn format_library_name(refs: &PyRefs<'_>, library: &str) -> Result<String, PyReadError> {
    let result = refs
        .format_library_name
        .call1((library,))
        .map_err(|source| PyReadError::Attr {
            attr: "format_library_name(library)",
            source,
        })?;
    py_str(&result)
}

/// Resolve the JS tag/component name for a generic Component, returning
/// the interned symbol. Bare HTML tags (`title`, `meta`) get quoted to
/// match the legacy emitter (`jsx("title", …)`).
fn resolve_tag_symbol(component: &Bound<'_, PyAny>) -> Result<Symbol, PyReadError> {
    let alias = component.getattr("alias").ok().filter(|v| !v.is_none());
    let tag = component.getattr("tag").ok().filter(|v| !v.is_none());
    let raw_name = match (&alias, &tag) {
        (Some(a), _) => py_str(a)?,
        (None, Some(t)) => py_str(t)?,
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

fn is_js_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !(first.is_ascii_alphabetic() || first == '_' || first == '$') {
        return false;
    }
    for c in chars {
        if !(c.is_ascii_alphanumeric() || c == '_' || c == '$') {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod state_ident_tests {
    use super::find_state_idents;

    #[test]
    fn finds_single_state() {
        let s = find_state_idents("reflex___state____state__counter_state.value");
        assert_eq!(s, vec!["reflex___state____state__counter_state"]);
    }

    #[test]
    fn ignores_partial_prefix() {
        assert!(find_state_idents("notthestate__counter_state").is_empty());
    }

    #[test]
    fn finds_multiple_distinct() {
        let s = find_state_idents(
            "reflex___state____state__a_state + reflex___state____state__b_state",
        );
        assert_eq!(
            s,
            vec![
                "reflex___state____state__a_state".to_owned(),
                "reflex___state____state__b_state".to_owned(),
            ]
        );
    }

    #[test]
    fn requires_state_suffix() {
        assert!(find_state_idents("reflex___state____state__not_terminated").is_empty());
    }
}
