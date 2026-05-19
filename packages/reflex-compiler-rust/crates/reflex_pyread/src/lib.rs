//! Small PyO3-backed helpers that remain after the two-phase split.
//!
//! Phase 1 (`reflex.compiler.ir.bridge.page_to_ir` on the Python side)
//! produces msgpack-packed IR; phase 2 (`reflex_codegen::emit_page` via
//! `CompilerSession.compile_page_from_bytes`) walks the bytes and emits
//! JSX. Neither phase needs to read Python `Component` PyObjects from
//! Rust.
//!
//! What still lives here:
//!
//! * [`memoize`] — `should_memoize` per-node decision, called from
//!   `reflex.compiler.rust_memo.walk_and_memoize` during phase 1.
//! * [`imports`] — `collect_all_imports` / `merge_imports_into`, the
//!   walker used to harvest NPM packages for `bun install`.
//! * [`pyo3_reader`] — the tiny shared helpers (`PyReadError`,
//!   `class_name`, `py_str`) the two surfaces above depend on.

#![forbid(unsafe_code)]

pub mod text;

#[cfg(feature = "pyo3")]
mod pyo3_reader;

#[cfg(feature = "pyo3")]
pub mod memoize;

#[cfg(feature = "pyo3")]
pub mod imports;

#[cfg(feature = "pyo3")]
pub use pyo3_reader::PyReadError;

#[cfg(feature = "pyo3")]
pub use memoize::{should_memoize, MemoRefs};

#[cfg(feature = "pyo3")]
pub use imports::{collect_all_imports, collect_all_imports_into, merge_imports_into};
