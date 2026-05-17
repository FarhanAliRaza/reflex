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

use std::cell::{Cell, RefCell};
use std::collections::HashMap;

use pyo3::prelude::*;

thread_local! {
    /// `{export_name -> (body PyObject, signature)}` for the page
    /// currently being read.
    pub static MEMO_BODIES: RefCell<HashMap<String, (PyObject, String)>>
        = RefCell::new(HashMap::new());

    /// Phase 2 Part B feature flag: when `true`, the `read_page` walk
    /// transforms memoize-candidate Components into `Component::MemoCall`
    /// IR nodes (registering their bodies into `MEMO_BODIES`). Defaults
    /// to `false` so the legacy Python `walk_and_memoize` pass keeps
    /// owning the transformation until Part D flips the default. Flipping
    /// while Python's pass is still active would double-wrap every
    /// candidate.
    pub static MEMOIZE_IN_RUST: Cell<bool> = const { Cell::new(false) };
}

/// Whether the Rust-side memoize transformation is enabled for the
/// current thread. See `MEMOIZE_IN_RUST` for the gating story.
pub fn memoize_enabled() -> bool {
    MEMOIZE_IN_RUST.with(|c| c.get())
}

/// Toggle the Rust-side memoize transformation on or off for the
/// current thread. Persists across `read_page` calls — the per-page
/// reset only touches the body collector, not this flag.
pub fn set_memoize_enabled(value: bool) {
    MEMOIZE_IN_RUST.with(|c| c.set(value));
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

#[cfg(test)]
mod tests {
    use super::{memoize_enabled, set_memoize_enabled};

    #[test]
    fn flag_defaults_off() {
        // Fresh thread-local state — the constant initializer is `false`.
        assert!(!memoize_enabled());
    }

    #[test]
    fn flag_roundtrips() {
        set_memoize_enabled(true);
        assert!(memoize_enabled());
        set_memoize_enabled(false);
        assert!(!memoize_enabled());
    }
}
