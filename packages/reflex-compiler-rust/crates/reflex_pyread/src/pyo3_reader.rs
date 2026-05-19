//! Small PyO3 helpers shared by the remaining pyread-side surfaces
//! (`memoize::should_memoize`, `imports::collect_all_imports`).
//!
//! The full `read_page` reader this file once hosted is gone — the
//! two-phase pipeline (`reflex.compiler.ir.bridge.page_to_ir` →
//! `CompilerSession.compile_page_from_bytes`) replaced it. What's left
//! here is the minimum surface those two remaining callers need:
//! `PyReadError`, `class_name`, `py_str`.

use pyo3::prelude::*;
use pyo3::types::{PyAnyMethods, PyString, PyStringMethods, PyTypeMethods};

/// Errors raised by the remaining pyread helpers.
///
/// Surfaced as Python `ValueError`s via `CompilerSession`.
#[derive(Debug, thiserror::Error)]
pub enum PyReadError {
    #[error("pyo3 attribute error on `{attr}`: {source}")]
    Attr {
        attr: &'static str,
        #[source]
        source: PyErr,
    },
    #[error("type mismatch on `{attr}`: expected {expected}, got {got}")]
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

/// `str(obj)` returning an owned `String`. Used wherever the caller
/// needs a Rust string but the Python value isn't already a `str`.
pub(crate) fn py_str(obj: &Bound<'_, PyAny>) -> Result<String, PyReadError> {
    obj.str()
        .map_err(|source| PyReadError::Attr {
            attr: "str()",
            source,
        })
        .and_then(|s| {
            s.to_str()
                .map(str::to_owned)
                .map_err(|source| PyReadError::Attr {
                    attr: "PyString::to_str",
                    source,
                })
        })
}

/// `type(component).__name__` as an owned `String`. Used as the
/// Component subclass dispatch key.
pub(crate) fn class_name(component: &Bound<'_, PyAny>) -> Result<String, PyReadError> {
    let ty = component.get_type();
    let name = ty.name().map_err(|source| PyReadError::Attr {
        attr: "type.__name__",
        source,
    })?;
    name.to_str()
        .map(str::to_owned)
        .map_err(|source| PyReadError::Attr {
            attr: "type.__name__.to_str",
            source,
        })
}

// PyString is re-exported by pyo3::types so callers don't have to chase
// the pyo3 docs to find it.
#[allow(dead_code)]
const _: fn() = || {
    let _: Option<&PyString> = None;
};
