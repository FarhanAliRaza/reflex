//! PyO3 entry for the reflex-compiler-rust wheel.
//!
//! Exposes `CompilerSession`, the two-phase entry point:
//!   - Phase 1 (Python): `reflex.compiler.ir.bridge.page_to_ir` →
//!     msgpack-packed `Page` IR.
//!   - Phase 2 (Rust): `compile_page_from_bytes` / `compile_memo_from_bytes`
//!     parse the IR and emit JSX without calling back into Python.

mod session;

use pyo3::prelude::*;

#[pymodule]
fn _native(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<session::CompilerSession>()?;
    Ok(())
}
