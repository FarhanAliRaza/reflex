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
    /// `getattr("id")` check + `mark_needs_ref`.
    pub needs_ref_ns: u64,
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
}

thread_local! {
    pub static TIMINGS: RefCell<PhaseTimings> = const { RefCell::new(PhaseTimings {
        class_name_ns: 0,
        resolve_tag_ns: 0,
        import_alias_ns: 0,
        needs_ref_ns: 0,
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
            Field::NeedsRef => t.needs_ref_ns += elapsed_ns,
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
        }
    });
}

#[derive(Clone, Copy)]
pub enum Field {
    ClassName,
    ResolveTag,
    ImportAlias,
    NeedsRef,
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
}

#[derive(Clone, Copy)]
pub enum Counter {
    Node,
    Element,
    Var,
    Prop,
    EventHandler,
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

/// Standalone timing namespace for the `collect_all_imports_into` walk.
///
/// `collect_all_imports_into` is a separate Rust entry point — it does
/// not go through `read_page` and therefore never touches the
/// [`PhaseTimings`] cell above. Without its own namespace the 3.10 ms
/// per page it costs at scale=1 was a black box. The fields below
/// mirror the leaf operations inside `walk_into` (see `imports.rs`)
/// so a Python-side benchmark can attribute the wrapper time to
/// specific sub-steps.
pub mod import_timing {
    use std::cell::RefCell;
    use std::time::Instant;

    /// Per-phase nanosecond counters for the import-collection walk.
    /// All spans are leaf-only — nested recursion is excluded — so the
    /// fields sum to ~`walk_total_ns` (modulo loop control flow).
    #[derive(Clone, Copy, Default, Debug)]
    pub struct ImportTimings {
        /// End-to-end `collect_all_imports_into` time.
        pub walk_total_ns: u64,
        /// Per-node `_get_imports()` PyO3 call + dict downcast + iteration setup.
        pub get_imports_call_ns: u64,
        /// Per-entry library-name read + `$/utils/...` prefix rewrite.
        pub lib_prefix_transform_ns: u64,
        /// Per-entry `append_items` — merges into the caller's dict.
        pub merge_into_target_ns: u64,
        /// Per-node `getattr("children")` + `iter()` setup (excludes child recursion).
        pub children_iter_ns: u64,
        /// Per-node `_get_components_in_props()` PyO3 call + iter setup
        /// (excludes prop-component recursion).
        pub prop_components_call_ns: u64,

        /// Tree nodes the walk visited (one per `walk_into` entry).
        pub node_count: u64,
        /// Vars handled implicitly via `_get_imports()` results — bumped
        /// per import entry observed.
        pub var_count: u64,
        /// `dict[str, list[ImportVar]]` entries appended into the target.
        pub import_entry_count: u64,
    }

    thread_local! {
        pub static IMPORT_TIMINGS: RefCell<ImportTimings> = const { RefCell::new(ImportTimings {
            walk_total_ns: 0,
            get_imports_call_ns: 0,
            lib_prefix_transform_ns: 0,
            merge_into_target_ns: 0,
            children_iter_ns: 0,
            prop_components_call_ns: 0,
            node_count: 0,
            var_count: 0,
            import_entry_count: 0,
        }) };
    }

    pub fn reset() {
        IMPORT_TIMINGS.with(|cell| *cell.borrow_mut() = ImportTimings::default());
    }

    pub fn snapshot() -> ImportTimings {
        IMPORT_TIMINGS.with(|cell| *cell.borrow())
    }

    #[inline]
    pub fn add(field: Field, elapsed_ns: u64) {
        IMPORT_TIMINGS.with(|cell| {
            let mut t = cell.borrow_mut();
            match field {
                Field::WalkTotal => t.walk_total_ns += elapsed_ns,
                Field::GetImportsCall => t.get_imports_call_ns += elapsed_ns,
                Field::LibPrefixTransform => t.lib_prefix_transform_ns += elapsed_ns,
                Field::MergeIntoTarget => t.merge_into_target_ns += elapsed_ns,
                Field::ChildrenIter => t.children_iter_ns += elapsed_ns,
                Field::PropComponentsCall => t.prop_components_call_ns += elapsed_ns,
            }
        });
    }

    #[inline]
    pub fn incr(counter: Counter) {
        IMPORT_TIMINGS.with(|cell| {
            let mut t = cell.borrow_mut();
            match counter {
                Counter::Node => t.node_count += 1,
                Counter::Var => t.var_count += 1,
                Counter::ImportEntry => t.import_entry_count += 1,
            }
        });
    }

    #[inline]
    pub fn add_var(n: u64) {
        IMPORT_TIMINGS.with(|cell| cell.borrow_mut().var_count += n);
    }

    #[inline]
    pub fn add_entry(n: u64) {
        IMPORT_TIMINGS.with(|cell| cell.borrow_mut().import_entry_count += n);
    }

    #[derive(Clone, Copy)]
    pub enum Field {
        WalkTotal,
        GetImportsCall,
        LibPrefixTransform,
        MergeIntoTarget,
        ChildrenIter,
        PropComponentsCall,
    }

    #[derive(Clone, Copy)]
    pub enum Counter {
        Node,
        Var,
        ImportEntry,
    }

    /// RAII guard mirroring the parent module's `Span`.
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
}
