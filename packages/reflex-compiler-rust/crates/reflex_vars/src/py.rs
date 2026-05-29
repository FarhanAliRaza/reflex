//! PyO3 bindings exposing the Rust `Var` to Python — the spine of the Var
//! cutover.
//!
//! This is the first vertical slice: scalar literals (`int`, `float`, `str`,
//! `bool`, `None`) and raw vars, rendered byte-identically to the Python
//! `LiteralVar.create` / `Var` they replace. The acceptance gate is the golden
//! oracle (`tests/units/vars/var_golden.json`): the `lit_*` / `raw_var`
//! entries must match exactly.
//!
//! The class is registered into the existing `reflex_compiler_rust._native`
//! module (see `reflex_py`). Subsequent slices grow it toward the full
//! protocol (operators, typed subclasses, var_data propagation, casting).

// `useless_conversion` is a false positive in this module: clippy fires on the
// `?`-operator desugaring (`From::<PyErr>::from`) inside the `#[pyfunction]`
// macro-generated wrappers under pyo3 0.22, not on any explicit cast we write.
#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyFloat, PyInt, PyString};
use pyo3::PyTypeInfo;

/// A Rust-backed `Var`: a finalized JS expression, its Python `_var_type`, and
/// (eventually) its `VarData`. Scalars carry no var_data.
///
/// `subclass` so the Python typed facades can inherit from it during the
/// cutover; `frozen` to match the immutable Python `Var` dataclass.
#[pyclass(
    subclass,
    frozen,
    name = "RustVar",
    module = "reflex_compiler_rust._native"
)]
pub struct RustVar {
    js_expr: String,
    var_type: Py<PyAny>,
}

#[pymethods]
impl RustVar {
    /// The finalized JS expression (matches the Python `_js_expr` field).
    #[getter]
    fn _js_expr(&self) -> &str {
        &self.js_expr
    }

    /// The Python type object describing the var's value type.
    #[getter]
    fn _var_type(&self, py: Python<'_>) -> Py<PyAny> {
        self.var_type.clone_ref(py)
    }

    /// Aggregate VarData. Scalars carry none, so this is always `None` for the
    /// current slice (grows with the reactive/state slice).
    fn _get_all_var_data(&self) -> Option<PyObject> {
        None
    }

    /// String form == the JS expression (matches Python `Var.__str__`).
    fn __str__(&self) -> &str {
        &self.js_expr
    }
}

/// Render a Python string as a JS string literal (double-quoted, escaped).
///
/// Matches the corpus expectation: `hi` -> `"hi"`, `a"b` -> `"a\"b"`.
fn render_js_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            _ => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Build a scalar `RustVar` from a Python value, dispatching on its type.
///
/// Mirrors the scalar cases of `LiteralVar.create`. `bool` must be checked
/// before `int` (Python `bool` is a subclass of `int`).
///
/// Args:
///     py: The GIL token.
///     value: The Python scalar to wrap.
///
/// Returns:
///     A `RustVar` whose `_js_expr` / `_var_type` match the Python literal.
#[pyfunction]
pub fn rust_literal(py: Python<'_>, value: Bound<'_, PyAny>) -> PyResult<RustVar> {
    if value.is_none() {
        return Ok(RustVar {
            js_expr: "null".to_owned(),
            var_type: py.None(),
        });
    }
    // bool before int — bool is an int subclass in Python.
    if value.is_instance_of::<PyBool>() {
        let b = value.extract::<bool>()?;
        return Ok(RustVar {
            js_expr: if b { "true" } else { "false" }.to_owned(),
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
        });
    }
    if value.is_instance_of::<PyInt>() {
        let i = value.extract::<i64>()?;
        return Ok(RustVar {
            js_expr: i.to_string(),
            var_type: PyInt::type_object_bound(py).into_any().unbind(),
        });
    }
    if value.is_instance_of::<PyFloat>() {
        let f = value.extract::<f64>()?;
        return Ok(RustVar {
            js_expr: render_js_float(f),
            var_type: PyFloat::type_object_bound(py).into_any().unbind(),
        });
    }
    if value.is_instance_of::<PyString>() {
        let s = value.extract::<String>()?;
        return Ok(RustVar {
            js_expr: render_js_string(&s),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
        });
    }
    let type_name = value
        .get_type()
        .name()
        .map(|n| n.to_string())
        .unwrap_or_else(|_| "?".to_owned());
    Err(pyo3::exceptions::PyTypeError::new_err(format!(
        "rust_literal: unsupported scalar type {type_name}"
    )))
}

/// Build a raw `RustVar` from an explicit JS expression and var type.
///
/// Mirrors `Var(_js_expr=..., _var_type=...)` for the non-literal base case.
///
/// Args:
///     js_expr: The JS expression source.
///     var_type: The Python type object for the var.
///
/// Returns:
///     A `RustVar` carrying the given expression and type.
#[pyfunction]
pub fn rust_raw_var(js_expr: String, var_type: Py<PyAny>) -> RustVar {
    RustVar { js_expr, var_type }
}

/// Render an f64 as JS source. Integral floats keep a trailing `.0` only when
/// Python's `repr` would; for now this matches the corpus (`1.5` -> `1.5`).
fn render_js_float(f: f64) -> String {
    // Rust's f64 Display already yields the shortest round-trip form ("1.5").
    format!("{f}")
}

/// Register the Var bindings into the `_native` module.
///
/// Args:
///     m: The parent module to register into.
///
/// Returns:
///     `Ok(())` on success.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustVar>()?;
    m.add_function(wrap_pyfunction!(rust_literal, m)?)?;
    m.add_function(wrap_pyfunction!(rust_raw_var, m)?)?;
    Ok(())
}
