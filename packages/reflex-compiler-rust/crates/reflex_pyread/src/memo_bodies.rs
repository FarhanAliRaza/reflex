//! Thread-local collector for auto-memoize wrapper bodies discovered
//! during a `read_page` walk. See plan §0a Phase 2 Part C of the Rust
//! IR Memoize port.
//!
//! When `read_page` constructs a `MemoCall` IR node (Phase 2 Part B), it
//! stashes the corresponding wrapper-body PyObject + signature here so
//! the Python orchestrator can later emit the body modules without
//! re-walking the tree. Mirrors the
//! `walk_and_memoize` -> `memo_bodies: dict[str, (body, definition)]`
//! shape used today in `reflex/compiler/rust_memo.py`.
//!
//! Storage model parallels `timing.rs`'s `IMPORT_TIMINGS` cell: a
//! `RefCell<HashMap<...>>` in thread-local storage. `read_page` is
//! invoked from a single thread per session-instance call, so a
//! thread-local is sufficient and avoids growing `read_page`'s
//! signature. The per-page reset happens in
//! `CompilerSession::compile_page_from_component` (not in `read_page`
//! itself — `read_page` is also called recursively to emit memo body
//! modules and a reset there would clobber the page-level collection).
//!
//! Dedup semantics: keys are export names. If the same `name` is added
//! twice, the first entry wins — Phase 1B's hash parity guarantees that
//! the same `export_name` corresponds to the same body Component, so
//! skipping duplicates is correct and saves the second PyObject
//! reference.

use std::cell::RefCell;
use std::collections::HashMap;

use pyo3::prelude::*;

thread_local! {
    /// `{export_name -> (body PyObject, signature)}` for the page
    /// currently being read.
    pub static MEMO_BODIES: RefCell<HashMap<String, (PyObject, String)>>
        = RefCell::new(HashMap::new());
}

/// Clear the collector. Call at the start of every page compile so the
/// returned map reflects only the page just walked.
pub fn reset() {
    MEMO_BODIES.with(|cell| cell.borrow_mut().clear());
}

/// Register a memo wrapper body. Skips if `name` is already present:
/// same `export_name` guarantees same body (Phase 1B hash parity), so
/// the first insertion is canonical.
pub fn add(name: String, body: PyObject, signature: String) {
    MEMO_BODIES.with(|cell| {
        let mut map = cell.borrow_mut();
        map.entry(name).or_insert((body, signature));
    });
}

/// Drain every collected entry into a `Vec`, leaving the cell empty.
/// Callers convert to whatever Python shape they need.
pub fn drain() -> Vec<(String, PyObject, String)> {
    MEMO_BODIES.with(|cell| {
        let mut map = cell.borrow_mut();
        let drained: Vec<(String, PyObject, String)> = map
            .drain()
            .map(|(name, (body, sig))| (name, body, sig))
            .collect();
        drained
    })
}

/// Number of entries currently held. Test helper.
pub fn len() -> usize {
    MEMO_BODIES.with(|cell| cell.borrow().len())
}
