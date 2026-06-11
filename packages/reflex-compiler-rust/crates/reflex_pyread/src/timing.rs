//! Thread-local timing accumulator for diagnosing where the Rust read +
//! emit path spends its budget. Instrumented sections record into a
//! `RefCell<PhaseTimings>` cell; Python reads them through
//! `CompilerSession.last_phase_timings_ns()` between compiles.
//!
//! Each `Instant::now()` call is ~30 ns on Linux x86_64, so even a
//! 350-node tree only burns ~10 µs of measurement overhead — well
//! within signal range for a ~2 ms compile.
//!
//! Counters reset on every fresh `read_page` call so the values
//! reported reflect a single page's work.

use std::cell::RefCell;
use std::time::Instant;

/// Per-phase nanosecond counters. All spans are **leaf** — no nested
/// recursion is included in any counter, so values sum to roughly
/// `read_page_total_ns` (modulo loop control flow).
#[derive(Clone, Copy, Default, Debug)]
pub struct PhaseTimings {
    /// `type(component).__name__` dispatch lookup per node.
    pub class_name_ns: u64,
    /// `resolve_tag_symbol` — reads alias/tag/library/is_global_scope.
    pub resolve_tag_ns: u64,
    /// `import_alias_for` — reads library/tag/alias again (redundant
    /// with `resolve_tag_symbol`; isolating to confirm the cost).
    pub import_alias_ns: u64,
    /// `read_var_data` — Var._get_all_var_data + imports/hooks/deps decode.
    pub read_var_data_ns: u64,
    /// `refs.harvest.borrow_mut()` registrations (RefCell overhead).
    pub harvest_register_ns: u64,
    /// Pure-Rust JSX emit from IR (`emit_page_with_extras`).
    pub emit_ns: u64,
    /// `read_page` total, end-to-end.
    pub read_page_total_ns: u64,

    // ---- Finer-grained leaf spans, added to pin down per-element cost.
    /// `component.call_method0("get_props")` itself (per element).
    pub get_props_call_ns: u64,
    /// Per-prop `getattr(prop_name)` — reading each declared prop's value.
    pub prop_value_getattr_ns: u64,
    /// Per-element `getattr("children")` + initial `iter()` setup.
    pub children_attr_ns: u64,
    /// Per-element `getattr("event_triggers")` + dict downcast.
    pub event_triggers_attr_ns: u64,
    /// `isinstance(value, var_cls)` checks in `read_value`.
    pub isinstance_var_ns: u64,
    /// `read_value` non-Var dispatch (literal type probing).
    pub value_literal_dispatch_ns: u64,
    /// `read_attr_str(var, "_js_expr", ...)` for Var values.
    pub var_js_expr_attr_ns: u64,

    // ---- Counts so we can derive per-call costs.
    pub node_count: u64,
    pub element_count: u64,
    pub var_count: u64,
    pub prop_count: u64,
    pub event_handler_count: u64,

    // ---- Arena freeze (freeze.rs::freeze_into_slot) leaf spans. These
    // are the production path; the `read_*` fields above belong to the
    // legacy `read_page` walk. Each is leaf (no child recursion), so the
    // freeze sub-totals sum to roughly `freeze_total_ns` minus loop
    // control + the child-recursion descent.
    /// Whole `freeze_component` call (cumulative — includes children).
    pub freeze_total_ns: u64,
    /// class_name + classify + qualname + memo_mode + rename_props.
    pub freeze_structural_ns: u64,
    /// read_imports_summary + merge_prop_components_imports.
    pub freeze_imports_ns: u64,
    /// read_rendered_props (the per-declared-field getattr loop).
    pub freeze_props_ns: u64,
    /// read_style.
    pub freeze_style_ns: u64,
    /// read_event_callbacks.
    pub freeze_events_ns: u64,
    /// read_hooks_internal + read_hooks_user.
    pub freeze_hooks_ns: u64,
    /// read_custom_code + read_dynamic_imports + read_ref_name.
    pub freeze_optional_ns: u64,
    /// Slow import path only: build_imports_dict + merge + summary, for
    /// nodes the trivial fast-path gate rejected. `freeze_imports_ns`
    /// minus this is the fast-path (gate + library/tag) cost.
    pub freeze_imports_slow_ns: u64,
    /// Nodes that took the trivial-import fast path.
    pub imports_fast_count: u64,
    /// Nodes that fell through to the full build_imports_dict path.
    pub imports_slow_count: u64,
    /// Nodes whose `_get_hooks_internal` was assembled natively in Rust.
    pub hooks_fast_count: u64,
    /// Nodes that fell back to the Python `_get_hooks_internal()` call.
    pub hooks_slow_count: u64,
}

thread_local! {
    pub static TIMINGS: RefCell<PhaseTimings> = const { RefCell::new(PhaseTimings {
        class_name_ns: 0,
        resolve_tag_ns: 0,
        import_alias_ns: 0,
        read_var_data_ns: 0,
        harvest_register_ns: 0,
        emit_ns: 0,
        read_page_total_ns: 0,
        get_props_call_ns: 0,
        prop_value_getattr_ns: 0,
        children_attr_ns: 0,
        event_triggers_attr_ns: 0,
        isinstance_var_ns: 0,
        value_literal_dispatch_ns: 0,
        var_js_expr_attr_ns: 0,
        node_count: 0,
        element_count: 0,
        var_count: 0,
        prop_count: 0,
        event_handler_count: 0,
        freeze_total_ns: 0,
        freeze_structural_ns: 0,
        freeze_imports_ns: 0,
        freeze_props_ns: 0,
        freeze_style_ns: 0,
        freeze_events_ns: 0,
        freeze_hooks_ns: 0,
        freeze_optional_ns: 0,
        freeze_imports_slow_ns: 0,
        imports_fast_count: 0,
        imports_slow_count: 0,
        hooks_fast_count: 0,
        hooks_slow_count: 0,
    }) };
}

/// Reset all counters to zero. Call at the start of each compile so
/// reported values reflect the single page just compiled.
pub fn reset() {
    TIMINGS.with(|cell| *cell.borrow_mut() = PhaseTimings::default());
}

/// Snapshot the current counters.
pub fn snapshot() -> PhaseTimings {
    TIMINGS.with(|cell| *cell.borrow())
}

/// Add `elapsed` to the counter selected by `field`.
#[inline]
pub fn add(field: Field, elapsed_ns: u64) {
    TIMINGS.with(|cell| {
        let mut t = cell.borrow_mut();
        match field {
            Field::ClassName => t.class_name_ns += elapsed_ns,
            Field::ResolveTag => t.resolve_tag_ns += elapsed_ns,
            Field::ImportAlias => t.import_alias_ns += elapsed_ns,
            Field::ReadVarData => t.read_var_data_ns += elapsed_ns,
            Field::HarvestRegister => t.harvest_register_ns += elapsed_ns,
            Field::Emit => t.emit_ns += elapsed_ns,
            Field::ReadPageTotal => t.read_page_total_ns += elapsed_ns,
            Field::GetPropsCall => t.get_props_call_ns += elapsed_ns,
            Field::PropValueGetattr => t.prop_value_getattr_ns += elapsed_ns,
            Field::ChildrenAttr => t.children_attr_ns += elapsed_ns,
            Field::EventTriggersAttr => t.event_triggers_attr_ns += elapsed_ns,
            Field::IsInstanceVar => t.isinstance_var_ns += elapsed_ns,
            Field::ValueLiteralDispatch => t.value_literal_dispatch_ns += elapsed_ns,
            Field::VarJsExprAttr => t.var_js_expr_attr_ns += elapsed_ns,
            Field::FreezeTotal => t.freeze_total_ns += elapsed_ns,
            Field::FreezeStructural => t.freeze_structural_ns += elapsed_ns,
            Field::FreezeImports => t.freeze_imports_ns += elapsed_ns,
            Field::FreezeProps => t.freeze_props_ns += elapsed_ns,
            Field::FreezeStyle => t.freeze_style_ns += elapsed_ns,
            Field::FreezeEvents => t.freeze_events_ns += elapsed_ns,
            Field::FreezeHooks => t.freeze_hooks_ns += elapsed_ns,
            Field::FreezeOptional => t.freeze_optional_ns += elapsed_ns,
            Field::FreezeImportsSlow => t.freeze_imports_slow_ns += elapsed_ns,
        }
    });
}

/// Bump a count counter by 1.
#[inline]
pub fn incr(counter: Counter) {
    TIMINGS.with(|cell| {
        let mut t = cell.borrow_mut();
        match counter {
            Counter::Node => t.node_count += 1,
            Counter::Element => t.element_count += 1,
            Counter::Var => t.var_count += 1,
            Counter::Prop => t.prop_count += 1,
            Counter::EventHandler => t.event_handler_count += 1,
            Counter::ImportsFast => t.imports_fast_count += 1,
            Counter::ImportsSlow => t.imports_slow_count += 1,
        }
    });
}

#[derive(Clone, Copy)]
pub enum Field {
    ClassName,
    ResolveTag,
    ImportAlias,
    ReadVarData,
    HarvestRegister,
    Emit,
    ReadPageTotal,
    GetPropsCall,
    PropValueGetattr,
    ChildrenAttr,
    EventTriggersAttr,
    IsInstanceVar,
    ValueLiteralDispatch,
    VarJsExprAttr,
    FreezeTotal,
    FreezeStructural,
    FreezeImports,
    FreezeProps,
    FreezeStyle,
    FreezeEvents,
    FreezeHooks,
    FreezeOptional,
    FreezeImportsSlow,
}

#[derive(Clone, Copy)]
pub enum Counter {
    Node,
    Element,
    Var,
    Prop,
    EventHandler,
    ImportsFast,
    ImportsSlow,
}

/// RAII guard that adds the elapsed time to `field` when dropped.
/// Cheaper to type than `let t = Instant::now(); …; add(field, …)` at
/// every site.
pub struct Span {
    start: Instant,
    field: Field,
}

impl Span {
    #[inline]
    pub fn new(field: Field) -> Self {
        Self {
            start: Instant::now(),
            field,
        }
    }
}

impl Drop for Span {
    #[inline]
    fn drop(&mut self) {
        let ns = self.start.elapsed().as_nanos() as u64;
        add(self.field, ns);
    }
}
