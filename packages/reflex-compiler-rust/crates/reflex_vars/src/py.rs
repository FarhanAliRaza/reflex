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

use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyFloat, PyInt, PyList, PyString, PyType};
use pyo3::PyTypeInfo;

use crate::var::Var;
use crate::var_data::{normalize_import_lib, ImportVar, VarData};

/// f-string marker tags — must match `REFLEX_VAR_OPENING_TAG` /
/// `REFLEX_VAR_CLOSING_TAG` (constants/base.py) so a RustVar can be formatted
/// into a Python f-string and decoded by either side during the transition.
const VAR_OPENING_TAG: &str = "<reflex.Var>";
const VAR_CLOSING_TAG: &str = "</reflex.Var>";

/// A registered var's recoverable state: its js_expr and aggregate var_data.
type RegisteredVar = (String, Option<VarData>);

/// Registry backing the f-string marker protocol: `__format__` stashes a var's
/// `(js_expr, var_data)` under a unique id and emits a marker carrying that id;
/// `rust_create_string` looks it back up while decoding. Mirrors Python's
/// `_global_vars` dict (here keyed by a counter rather than `hash`).
fn var_registry() -> &'static Mutex<HashMap<i64, RegisteredVar>> {
    static REGISTRY: OnceLock<Mutex<HashMap<i64, RegisteredVar>>> = OnceLock::new();
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

static VAR_COUNTER: AtomicI64 = AtomicI64::new(1);

/// A Rust-backed `Var`: a finalized JS expression, its Python `_var_type`, and
/// its aggregate `VarData`.
///
/// `var_data` stores the **eager** `_get_all_var_data()` result: a leaf carries
/// its seeded VarData; an operation carries `merge(own, *operand_get_alls)`
/// where `own = merge(*operand_get_alls)`. That double-merge reproduces the
/// import multiplicity the Python Var produces (operations re-include each
/// operand's var_data, and imports concatenate without dedup).
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
    var_data: Option<VarData>,
}

#[pymethods]
impl RustVar {
    /// Construct a `Var` from a JS expression, type, and optional var_data —
    /// the drop-in for the Python `Var(_js_expr=, _var_type=, _var_data=)`
    /// dataclass constructor.
    ///
    /// Inline `<reflex.Var>` markers in `_js_expr` are decoded (tags stripped,
    /// the referenced vars' var_data merged in), matching `Var.__post_init__`'s
    /// call to `_decode_var_immutable`.
    #[new]
    #[pyo3(signature = (_js_expr, _var_type = None, _var_data = None))]
    fn new(
        py: Python<'_>,
        _js_expr: String,
        _var_type: Option<Py<PyAny>>,
        _var_data: Option<Bound<'_, PyAny>>,
    ) -> PyResult<RustVar> {
        let mut var_data = match _var_data {
            Some(vd) => convert_var_data(&vd)?,
            None => None,
        };
        let js_expr = if _js_expr.contains(VAR_OPENING_TAG) {
            let (clean, embedded) = decode_markers_inline(&_js_expr);
            var_data = VarData::merge([var_data.as_ref(), embedded.as_ref()])
                .ok()
                .flatten();
            clean
        } else {
            _js_expr
        };
        let var_type = match _var_type {
            Some(t) if !t.bind(py).is_none() => t,
            _ => py.import_bound("typing")?.getattr("Any")?.unbind(),
        };
        Ok(RustVar {
            js_expr,
            var_type,
            var_data,
        })
    }

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

    /// Aggregate VarData (`merge` of this var's own data and its operands'),
    /// or `None` when the var carries none (scalars). Matches the Python
    /// `_get_all_var_data()`.
    fn _get_all_var_data(&self) -> Option<PyVarData> {
        self.var_data.clone().map(|vd| PyVarData { inner: vd })
    }

    /// String form == the JS expression (matches Python `Var.__str__`).
    fn __str__(&self) -> &str {
        &self.js_expr
    }

    /// Hash (matches `Var.__hash__` = `hash((_js_expr, _var_type, _var_data))`).
    /// Defined explicitly because `__richcmp__` otherwise nulls `__hash__`.
    fn __hash__(&self, py: Python<'_>) -> PyResult<isize> {
        let vd: Py<PyAny> = match &self.var_data {
            Some(v) => Bound::new(py, PyVarData { inner: v.clone() })?
                .into_any()
                .unbind(),
            None => py.None(),
        };
        let tup = pyo3::types::PyTuple::new_bound(
            py,
            [
                self.js_expr.clone().into_py(py),
                self.var_type.clone_ref(py),
                vd,
            ],
        );
        tup.hash()
    }

    /// Structural equality (matches `Var.equals`): same js_expr, var_type, and
    /// aggregate var_data.
    fn equals(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<bool> {
        let Ok(ojs) = other.getattr("_js_expr") else {
            return Ok(false);
        };
        if ojs.str()?.to_string() != self.js_expr {
            return Ok(false);
        }
        if !self.var_type.bind(py).eq(other.getattr("_var_type")?)? {
            return Ok(false);
        }
        let my_vd: Py<PyAny> = match &self.var_data {
            Some(v) => Bound::new(py, PyVarData { inner: v.clone() })?
                .into_any()
                .unbind(),
            None => py.None(),
        };
        my_vd.bind(py).eq(other.call_method0("_get_all_var_data")?)
    }

    /// Pickle support: reconstruct via the constructor (state persistence
    /// pickles/dills Vars embedded in state).
    fn __reduce__(&self, py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        let cls = RustVar::type_object_bound(py).into_any().unbind();
        let vd: Py<PyAny> = match &self.var_data {
            Some(v) => Bound::new(py, PyVarData { inner: v.clone() })?
                .into_any()
                .unbind(),
            None => py.None(),
        };
        let args = (self.js_expr.clone(), self.var_type.clone_ref(py), vd);
        Ok((cls, args.into_py(py)))
    }

    /// Format into an f-string fragment (matches `Var.__format__`): register
    /// this var under a fresh id and emit `<reflex.Var>{id}</reflex.Var>{js}`.
    ///
    /// Registers into the **Python** ``_global_vars`` dict (the shared registry
    /// Python's ``_decode_var_immutable`` and ``LiteralStringVar.create`` read),
    /// so a Rust var formatted into a Python f-string / operation decodes
    /// correctly — and also into the Rust registry for ``rust_create_string``.
    fn __format__(&self, py: Python<'_>, _format_spec: &str) -> PyResult<String> {
        let id = VAR_COUNTER.fetch_add(1, Ordering::Relaxed);
        if let Ok(mut reg) = var_registry().lock() {
            reg.insert(id, (self.js_expr.clone(), self.var_data.clone()));
        }
        let clone = RustVar {
            js_expr: self.js_expr.clone(),
            var_type: self.var_type.clone_ref(py),
            var_data: self.var_data.clone(),
        };
        py.import_bound("reflex_base.vars.base")?
            .getattr("_global_vars")?
            .set_item(id, Py::new(py, clone)?)?;
        Ok(format!(
            "{VAR_OPENING_TAG}{id}{VAR_CLOSING_TAG}{}",
            self.js_expr
        ))
    }

    // --- number operators ---
    // These mirror `NumberVar` in `vars/number.py`. The operand `{lhs}`/`{rhs}`
    // is each var's `_js_expr`; arithmetic result type is `unionize(lhs, rhs)`.
    // var_data propagation lands in the next slice (this slice pins the JS
    // rendering + var_type).

    fn __add__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        match self.type_label(py).as_deref() {
            Some("str") => self.str_concat(py, &other, false),
            Some("list") => self.array_concat(py, &other),
            _ => self.arith(py, &other, "+", false),
        }
    }

    fn __radd__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        if self.is_str(py) {
            return self.str_concat(py, &other, true);
        }
        self.arith(py, &other, "+", true)
    }

    fn __sub__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        self.arith(py, &other, "-", false)
    }

    fn __rsub__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        self.arith(py, &other, "-", true)
    }

    fn __mul__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        if self.is_str(py) {
            return self.str_mul(py, &other);
        }
        self.arith(py, &other, "*", false)
    }

    fn __rmul__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        if self.is_str(py) {
            return self.str_mul(py, &other);
        }
        self.arith(py, &other, "*", true)
    }

    fn __truediv__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        self.arith(py, &other, "/", false)
    }

    fn __mod__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        self.arith(py, &other, "%", false)
    }

    fn __pow__(
        &self,
        py: Python<'_>,
        other: Bound<'_, PyAny>,
        _modulo: Option<Bound<'_, PyAny>>,
    ) -> PyResult<RustVar> {
        self.arith(py, &other, "**", false)
    }

    fn __floordiv__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (ojs, ot, ovd) = operand_parts(py, &other)?;
        Ok(RustVar {
            js_expr: format!("Math.floor({} / {ojs})", self.js_expr),
            var_type: unionize(py, &self.var_type, &ot),
            var_data: binary_var_data(&self.var_data, &ovd),
        })
    }

    fn __neg__(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("-({})", self.js_expr),
            var_type: self.var_type.clone_ref(py),
            var_data: unary_var_data(&self.var_data),
        }
    }

    fn __abs__(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("Math.abs({})", self.js_expr),
            var_type: self.var_type.clone_ref(py),
            var_data: unary_var_data(&self.var_data),
        }
    }

    fn __invert__(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("!({})", self.js_expr),
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
            var_data: unary_var_data(&self.var_data),
        }
    }

    fn __and__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (ojs, ot, ovd) = operand_parts(py, &other)?;
        Ok(RustVar {
            js_expr: format!("({} && {ojs})", self.js_expr),
            var_type: unionize(py, &self.var_type, &ot),
            var_data: binary_var_data(&self.var_data, &ovd),
        })
    }

    fn __or__(&self, py: Python<'_>, other: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (ojs, ot, ovd) = operand_parts(py, &other)?;
        Ok(RustVar {
            js_expr: format!("({} || {ojs})", self.js_expr),
            var_type: unionize(py, &self.var_type, &ot),
            var_data: binary_var_data(&self.var_data, &ovd),
        })
    }

    /// Comparisons (`<`, `<=`, `>`, `>=`, `==`, `!=`) — all return a boolean
    /// var. Equality wraps each operand with `?.valueOf?.()` (matches
    /// `equal_operation` / `not_equal_operation`).
    fn __richcmp__(
        &self,
        py: Python<'_>,
        other: Bound<'_, PyAny>,
        op: CompareOp,
    ) -> PyResult<RustVar> {
        let (ojs, _ot, ovd) = operand_parts(py, &other)?;
        let lhs = &self.js_expr;
        let js = match op {
            CompareOp::Lt => format!("({lhs} < {ojs})"),
            CompareOp::Le => format!("({lhs} <= {ojs})"),
            CompareOp::Gt => format!("({lhs} > {ojs})"),
            CompareOp::Ge => format!("({lhs} >= {ojs})"),
            CompareOp::Eq => format!("({lhs}?.valueOf?.() === {ojs}?.valueOf?.())"),
            CompareOp::Ne => format!("({lhs}?.valueOf?.() !== {ojs}?.valueOf?.())"),
        };
        Ok(RustVar {
            js_expr: js,
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
            var_data: binary_var_data(&self.var_data, &ovd),
        })
    }

    // --- casting ---

    /// Cast to another var type (`Var.to`). Keeps the JS expression and
    /// var_data; only the var_type changes (matches `ToOperation`, which merges
    /// var_data exactly once).
    fn to(&self, output: Py<PyAny>) -> RustVar {
        RustVar {
            js_expr: self.js_expr.clone(),
            var_type: output,
            var_data: var_op_plain(&[&self.var_data]),
        }
    }

    // --- string methods (mirror StringVar in vars/sequence.py) ---
    // These assume a string receiver; the typed Python facade dispatches by
    // type, which the cutover preserves via the type-tagged var_type.

    fn lower(&self, py: Python<'_>) -> RustVar {
        self.str_unary_op(py, |s| format!("{s}.toLowerCase()"))
    }

    fn upper(&self, py: Python<'_>) -> RustVar {
        self.str_unary_op(py, |s| format!("{s}.toUpperCase()"))
    }

    fn capitalize(&self, py: Python<'_>) -> RustVar {
        self.str_unary_op(py, |s| {
            format!("(((s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase())({s}))")
        })
    }

    /// `contains` dispatches by receiver type: strings/arrays use
    /// `.includes(x)`, objects use `.hasOwnProperty(key)`. All return bool with
    /// doubling var_data.
    fn contains(&self, py: Python<'_>, needle: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (njs, _nt, nvd) = operand_parts(py, &needle)?;
        let js = if self.type_label(py).as_deref() == Some("dict") {
            format!("{}.hasOwnProperty({njs})", self.js_expr)
        } else {
            format!("{}.includes({njs})", self.js_expr)
        };
        Ok(RustVar {
            js_expr: js,
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data, &nvd]),
        })
    }

    fn startswith(&self, py: Python<'_>, prefix: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (pjs, _pt, pvd) = operand_parts(py, &prefix)?;
        Ok(RustVar {
            js_expr: format!("{}.startsWith({pjs})", self.js_expr),
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data, &pvd]),
        })
    }

    /// Split into an array. `string_split_operation`: `{s}.split({sep})`.
    #[pyo3(signature = (separator = None))]
    fn split(&self, py: Python<'_>, separator: Option<Bound<'_, PyAny>>) -> PyResult<RustVar> {
        self.str_split(py, separator.as_ref())
    }

    /// `length` dispatches by type: a string is `split("").length` (two
    /// stacked doubling ops -> 8 imports), an array is `{arr}.length` (one ->
    /// 4). Both return int.
    fn length(&self, py: Python<'_>) -> PyResult<RustVar> {
        let (js, data) = if self.is_str(py) {
            let split = self.str_split(py, None)?;
            (
                format!("{}.length", split.js_expr),
                var_op_doubling(&[&split.var_data]),
            )
        } else {
            (
                format!("{}.length", self.js_expr),
                var_op_doubling(&[&self.var_data]),
            )
        };
        Ok(RustVar {
            js_expr: js,
            var_type: PyInt::type_object_bound(py).into_any().unbind(),
            var_data: data,
        })
    }

    /// Reverse an array: `{arr}.slice().reverse()`, keeps the array's type,
    /// doubling.
    fn reverse(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("{}.slice().reverse()", self.js_expr),
            var_type: self.var_type.clone_ref(py),
            var_data: var_op_doubling(&[&self.var_data]),
        }
    }

    /// Join an array into a string: `{arr}.join({sep})`, str result, doubling.
    #[pyo3(signature = (separator = None))]
    fn join(&self, py: Python<'_>, separator: Option<Bound<'_, PyAny>>) -> PyResult<RustVar> {
        let (sjs, svd) = match separator {
            Some(s) => {
                let (js, _t, vd) = operand_parts(py, &s)?;
                (js, vd)
            }
            None => ("\"\"".to_owned(), None),
        };
        Ok(RustVar {
            js_expr: format!("{}.join({sjs})", self.js_expr),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data, &svd]),
        })
    }

    /// Object keys: `Object.keys({obj} ?? {})`, list result, doubling.
    fn keys(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("Object.keys({} ?? {{}})", self.js_expr),
            var_type: PyList::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data]),
        }
    }

    /// Object values: `Object.values({obj} ?? {})`, list result, doubling.
    fn values(&self, py: Python<'_>) -> RustVar {
        RustVar {
            js_expr: format!("Object.values({} ?? {{}})", self.js_expr),
            var_type: PyList::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data]),
        }
    }

    /// Item access dispatches by receiver type: a string uses
    /// `{s}?.at?.({i})` (str, doubling), an array uses `{a}?.at?.({i})`
    /// (element type, plain), an object uses `{o}?.[{k}]` (value type, plain).
    fn __getitem__(&self, py: Python<'_>, index: Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (ijs, _it, ivd) = operand_parts(py, &index)?;
        match self.type_label(py).as_deref() {
            Some("str") => Ok(RustVar {
                js_expr: format!("{}?.at?.({ijs})", self.js_expr),
                var_type: PyString::type_object_bound(py).into_any().unbind(),
                var_data: var_op_doubling(&[&self.var_data, &ivd]),
            }),
            Some("dict") => Ok(RustVar {
                js_expr: format!("{}?.[{ijs}]", self.js_expr),
                var_type: self.value_type(py, 1),
                var_data: var_op_plain(&[&self.var_data, &ivd]),
            }),
            _ => Ok(RustVar {
                js_expr: format!("{}?.at?.({ijs})", self.js_expr),
                var_type: self.value_type(py, 0),
                var_data: var_op_plain(&[&self.var_data, &ivd]),
            }),
        }
    }

    /// Attribute-as-item access on an **object** var: `{o}?.["name"]`. Mirrors
    /// `ObjectVar.__getattr__`. Restricted to dict/object vars; on any other
    /// var type (and for underscore/dunder names) this raises `AttributeError`
    /// so a missing Var-protocol method surfaces cleanly instead of becoming a
    /// bogus item access.
    fn __getattr__(&self, py: Python<'_>, name: String) -> PyResult<RustVar> {
        if name.starts_with('_') || self.type_label(py).as_deref() != Some("dict") {
            return Err(pyo3::exceptions::PyAttributeError::new_err(name));
        }
        Ok(RustVar {
            js_expr: format!("{}?.[{}]", self.js_expr, render_js_string(&name)),
            var_type: self.value_type(py, 1),
            var_data: var_op_plain(&[&self.var_data]),
        })
    }
}

impl RustVar {
    /// Whether this var's type is the Python `str` builtin.
    fn is_str(&self, py: Python<'_>) -> bool {
        self.var_type
            .bind(py)
            .is(&PyString::type_object_bound(py).into_any())
    }

    /// The `__name__` of this var's type (e.g. "str", "list", "dict"), used to
    /// dispatch type-specific methods. `None` if the type has no `__name__`.
    fn type_label(&self, py: Python<'_>) -> Option<String> {
        self.var_type
            .bind(py)
            .getattr("__name__")
            .ok()
            .and_then(|n| n.extract::<String>().ok())
    }

    /// The element/value type of a container var: `var_type.__args__[idx]`
    /// (index 0 for sequences, 1 for mappings). Falls back to the container
    /// type itself when there are no type args.
    fn value_type(&self, py: Python<'_>, idx: usize) -> Py<PyAny> {
        self.var_type
            .bind(py)
            .getattr("__args__")
            .ok()
            .and_then(|args| args.get_item(idx).ok())
            .map(|t| t.unbind())
            .unwrap_or_else(|| self.var_type.clone_ref(py))
    }

    /// Array concatenation (`array_concat_operation`): `[...{a}, ...{b}]`. The
    /// result type is `a_type | b_type` (computed via Python's `|` so the
    /// rendered type matches exactly), doubling var_data.
    fn array_concat(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<RustVar> {
        let (ojs, ot, ovd) = operand_parts(py, other)?;
        let var_type = self
            .var_type
            .bind(py)
            .call_method1("__or__", (ot,))
            .map(|t| t.unbind())
            .unwrap_or_else(|_| self.var_type.clone_ref(py));
        Ok(RustVar {
            js_expr: format!("[...{}, ...{ojs}]", self.js_expr),
            var_type,
            var_data: var_op_doubling(&[&self.var_data, &ovd]),
        })
    }

    /// Build a unary string→string op `f(self)` with doubling var_data.
    fn str_unary_op(&self, py: Python<'_>, render: impl Fn(&str) -> String) -> RustVar {
        RustVar {
            js_expr: render(&self.js_expr),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data]),
        }
    }

    /// `string_split_operation`: `{s}.split({sep})`, list result, doubling.
    /// A `None` separator defaults to the empty string (`split("")`).
    fn str_split(&self, py: Python<'_>, separator: Option<&Bound<'_, PyAny>>) -> PyResult<RustVar> {
        let (sjs, svd) = match separator {
            Some(s) => {
                let (js, _t, vd) = operand_parts(py, s)?;
                (js, vd)
            }
            None => ("\"\"".to_owned(), None),
        };
        Ok(RustVar {
            js_expr: format!("{}.split({sjs})", self.js_expr),
            var_type: PyList::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&self.var_data, &svd]),
        })
    }

    /// String concatenation (`ConcatVarOperation`): `({a}+{b})`, str, plain
    /// (single merge — no doubling, so the corpus `str_add` carries 2 imports).
    fn str_concat(
        &self,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        reflected: bool,
    ) -> PyResult<RustVar> {
        let (ojs, _ot, ovd) = operand_parts(py, other)?;
        let (a, b) = if reflected {
            (ojs.as_str(), self.js_expr.as_str())
        } else {
            (self.js_expr.as_str(), ojs.as_str())
        };
        Ok(RustVar {
            js_expr: format!("({a}+{b})"),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
            var_data: var_op_plain(&[&self.var_data, &ovd]),
        })
    }

    /// String repeat: `(self.split() * n).join("")` — three stacked doubling
    /// ops (split, repeat, join), so var_data multiplies three times (the
    /// corpus `str_mul` carries 16 imports).
    fn str_mul(&self, py: Python<'_>, n: &Bound<'_, PyAny>) -> PyResult<RustVar> {
        let split = self.str_split(py, None)?;
        let (njs, _nt, nvd) = operand_parts(py, n)?;
        let repeat = RustVar {
            js_expr: format!(
                "Array.from({{ length: {njs} }}).flatMap(() => {})",
                split.js_expr
            ),
            var_type: PyList::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&split.var_data, &nvd]),
        };
        Ok(RustVar {
            js_expr: format!("{}.join(\"\")", repeat.js_expr),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
            var_data: var_op_doubling(&[&repeat.var_data]),
        })
    }
    /// Build a binary arithmetic op `(lhs sym rhs)`, result type unionized.
    ///
    /// `reflected` swaps operand order (the `__r*__` reflected dunders), so
    /// `1 + var` renders `(1 + var)`.
    fn arith(
        &self,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        sym: &str,
        reflected: bool,
    ) -> PyResult<RustVar> {
        let (ojs, ot, ovd) = operand_parts(py, other)?;
        let (lhs, rhs) = if reflected {
            (ojs.as_str(), self.js_expr.as_str())
        } else {
            (self.js_expr.as_str(), ojs.as_str())
        };
        Ok(RustVar {
            js_expr: format!("({lhs} {sym} {rhs})"),
            var_type: unionize(py, &self.var_type, &ot),
            var_data: binary_var_data(&self.var_data, &ovd),
        })
    }
}

/// Extract an operand's `(js_expr, var_type)` for use in an operator.
///
/// A `RustVar` operand contributes its own expression/type; a Python scalar is
/// coerced through `rust_literal` (mirrors the `LiteralVar.create` the Python
/// operators apply to non-Var operands).
///
/// Args:
///     py: The GIL token.
///     value: The operand (a `RustVar` or a Python scalar).
///
/// Returns:
///     The operand's JS expression and Python var-type object.
fn operand_parts(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
) -> PyResult<(String, Py<PyAny>, Option<VarData>)> {
    if let Ok(rv) = value.downcast::<RustVar>() {
        let b = rv.borrow();
        return Ok((
            b.js_expr.clone(),
            b.var_type.clone_ref(py),
            b.var_data.clone(),
        ));
    }
    let lit = rust_literal(py, value.clone())?;
    Ok((lit.js_expr, lit.var_type, lit.var_data))
}

/// The aggregate var_data of a "doubling" var_operation.
///
/// Reproduces Python's `CustomVarOperation._cached_get_all_var_data`: every
/// operand appears once as a stored arg, plus once more inside `_return`
/// (because the JS template embeds it via `{x}`/`__format__`, which carries the
/// operand's var_data). So `get_all = merge(*args, merge(*args))`. Since
/// imports concatenate, each operand's imports appear twice — the 2/4/8/16
/// multiplicity the Python Var produces, and it stacks across composed ops.
fn var_op_doubling(args: &[&Option<VarData>]) -> Option<VarData> {
    let own = VarData::merge(args.iter().map(|a| a.as_ref()))
        .ok()
        .flatten();
    let mut parts: Vec<Option<&VarData>> = args.iter().map(|a| a.as_ref()).collect();
    parts.push(own.as_ref());
    VarData::merge(parts).ok().flatten()
}

/// The aggregate var_data of a "plain" operation — a single merge of operands,
/// no doubling.
///
/// Used where the JS template references operands via `{x!s}` (no embedded
/// var_data, e.g. `array_item`), and by `ToOperation` casts and
/// `ConcatVarOperation` (string `+` / f-strings), which merge their inputs
/// exactly once.
fn var_op_plain(args: &[&Option<VarData>]) -> Option<VarData> {
    VarData::merge(args.iter().map(|a| a.as_ref()))
        .ok()
        .flatten()
}

/// The aggregate var_data of a binary doubling op (both operands embedded).
fn binary_var_data(a: &Option<VarData>, b: &Option<VarData>) -> Option<VarData> {
    var_op_doubling(&[a, b])
}

/// The aggregate var_data of a unary doubling op.
fn unary_var_data(a: &Option<VarData>) -> Option<VarData> {
    var_op_doubling(&[a])
}

/// Combine two number var-types into the result type of an arithmetic op.
///
/// Mirrors `unionize` for the cases the corpus exercises: equal types collapse
/// to that type (`int+int -> int`, `float+float -> float`); a mixed
/// `int`/`float` pair widens to `float`. Anything else falls back to the left
/// type.
///
/// Args:
///     py: The GIL token.
///     a: The left var-type object.
///     b: The right var-type object.
///
/// Returns:
///     The unionized var-type object.
fn unionize(py: Python<'_>, a: &Py<PyAny>, b: &Py<PyAny>) -> Py<PyAny> {
    let ab = a.bind(py);
    let bb = b.bind(py);
    if ab.is(bb) {
        return a.clone_ref(py);
    }
    let float_ty = PyFloat::type_object_bound(py);
    let int_ty = PyInt::type_object_bound(py);
    let is_num = |o: &Bound<'_, PyAny>| o.is(&float_ty) || o.is(&int_ty);
    if is_num(ab) && is_num(bb) {
        return float_ty.into_any().unbind();
    }
    a.clone_ref(py)
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

/// Render a Python literal value to its JS source, recursing into lists/dicts.
///
/// Mirrors the rendering side of `LiteralVar.create`: scalars as in
/// `rust_literal`, lists as `[a, b, ...]`, dicts as `({ ["k"] : v, ... })`
/// (key as a bracketed JS string, matching `LiteralObjectVar`).
///
/// Args:
///     value: The Python value to render.
///
/// Returns:
///     The JS source for the value.
fn render_literal_js(value: &Bound<'_, PyAny>) -> PyResult<String> {
    if value.is_none() {
        return Ok("null".to_owned());
    }
    // bool before int — bool is an int subclass in Python.
    if value.is_instance_of::<PyBool>() {
        return Ok(if value.extract::<bool>()? {
            "true"
        } else {
            "false"
        }
        .to_owned());
    }
    if value.is_instance_of::<PyInt>() {
        return Ok(value.extract::<i64>()?.to_string());
    }
    if value.is_instance_of::<PyFloat>() {
        return Ok(render_js_float(value.extract::<f64>()?));
    }
    if value.is_instance_of::<PyString>() {
        return Ok(render_js_string(&value.extract::<String>()?));
    }
    if let Ok(list) = value.downcast::<PyList>() {
        let items: PyResult<Vec<String>> = list.iter().map(|v| render_literal_js(&v)).collect();
        return Ok(format!("[{}]", items?.join(", ")));
    }
    if let Ok(dict) = value.downcast::<pyo3::types::PyDict>() {
        let mut pairs = Vec::with_capacity(dict.len());
        for (k, v) in dict.iter() {
            pairs.push(format!(
                "[{}] : {}",
                render_literal_js(&k)?,
                render_literal_js(&v)?
            ));
        }
        return Ok(if pairs.is_empty() {
            "({  })".to_owned()
        } else {
            format!("({{ {} }})", pairs.join(", "))
        });
    }
    let type_name = value
        .get_type()
        .name()
        .map(|n| n.to_string())
        .unwrap_or_else(|_| "?".to_owned());
    Err(pyo3::exceptions::PyTypeError::new_err(format!(
        "rust_literal: unsupported literal type {type_name}"
    )))
}

/// The `_var_type` object for a literal value (matches `figure_out_type` for
/// the cases the corpus exercises): scalars map to their builtin type, lists to
/// `typing.Sequence`, dicts to `typing.Mapping`.
fn literal_var_type(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_none() {
        return Ok(py.None());
    }
    if value.is_instance_of::<PyBool>() {
        return Ok(PyBool::type_object_bound(py).into_any().unbind());
    }
    if value.is_instance_of::<PyInt>() {
        return Ok(PyInt::type_object_bound(py).into_any().unbind());
    }
    if value.is_instance_of::<PyFloat>() {
        return Ok(PyFloat::type_object_bound(py).into_any().unbind());
    }
    if value.is_instance_of::<PyString>() {
        return Ok(PyString::type_object_bound(py).into_any().unbind());
    }
    let typing = py.import_bound("typing")?;
    if value.is_instance_of::<PyList>() {
        return Ok(typing.getattr("Sequence")?.unbind());
    }
    if value.is_instance_of::<pyo3::types::PyDict>() {
        return Ok(typing.getattr("Mapping")?.unbind());
    }
    Ok(py.None())
}

/// Build a literal `RustVar` from a Python value (scalar, list, or dict).
///
/// Mirrors `LiteralVar.create` for plain values: renders the JS source and
/// assigns the literal var type. Literals carry no var_data.
///
/// Args:
///     py: The GIL token.
///     value: The Python value to wrap.
///
/// Returns:
///     A `RustVar` whose `_js_expr` / `_var_type` match the Python literal.
#[pyfunction]
pub fn rust_literal(py: Python<'_>, value: Bound<'_, PyAny>) -> PyResult<RustVar> {
    Ok(RustVar {
        js_expr: render_literal_js(&value)?,
        var_type: literal_var_type(py, &value)?,
        var_data: None,
    })
}

/// Build a raw `RustVar` from an explicit JS expression and var type.
///
/// Mirrors `Var(_js_expr=..., _var_type=...)` for the non-literal base case.
/// Carries no var_data; use `rust_from_python_var` to seed a reactive leaf.
///
/// Args:
///     js_expr: The JS expression source.
///     var_type: The Python type object for the var.
///
/// Returns:
///     A `RustVar` carrying the given expression and type.
#[pyfunction]
pub fn rust_raw_var(js_expr: String, var_type: Py<PyAny>) -> RustVar {
    RustVar {
        js_expr,
        var_type,
        var_data: None,
    }
}

/// Seed a `RustVar` from an existing Python `Var` (e.g. a state field).
///
/// Copies the Python var's `_js_expr`, `_var_type`, and aggregate
/// `_get_all_var_data()` (converted to a Rust `VarData`). This is the bridge
/// used while the leaf-creation path (state-name mangling, hook synthesis)
/// still lives in Python: it lets Rust operators compose over a reactive leaf
/// and reproduce its var_data exactly.
///
/// Args:
///     py_var: The Python `Var` to mirror.
///
/// Returns:
///     A `RustVar` equivalent to the Python var.
#[pyfunction]
pub fn rust_from_python_var(py_var: Bound<'_, PyAny>) -> PyResult<RustVar> {
    let js_expr: String = py_var.getattr("_js_expr")?.extract()?;
    let var_type = py_var.getattr("_var_type")?.unbind();
    let var_data = convert_var_data(&py_var.call_method0("_get_all_var_data")?)?;
    Ok(RustVar {
        js_expr,
        var_type,
        var_data,
    })
}

/// Convert a Python `VarData` (or `None`) into a Rust `VarData`.
///
/// Reads the fields the framework propagates: state, field_name, hooks,
/// imports (with their `ImportVar` attributes), and deps (kept as bare
/// expressions). `position` / `components` are out of scope for the corpus and
/// left at their defaults.
///
/// Args:
///     obj: The Python `VarData` object, or `None`.
///
/// Returns:
///     The converted `VarData`, or `None` when `obj` is `None`.
fn convert_var_data(obj: &Bound<'_, PyAny>) -> PyResult<Option<VarData>> {
    if obj.is_none() {
        return Ok(None);
    }
    let state: String = obj.getattr("state")?.extract().unwrap_or_default();
    let field_name: String = obj.getattr("field_name")?.extract().unwrap_or_default();

    let mut hooks: Vec<String> = Vec::new();
    for h in obj.getattr("hooks")?.iter()? {
        hooks.push(h?.extract()?);
    }

    let mut imports: Vec<(String, Vec<ImportVar>)> = Vec::new();
    for pair in obj.getattr("imports")?.iter()? {
        let pair = pair?;
        let lib: String = pair.get_item(0)?.extract()?;
        let mut vars: Vec<ImportVar> = Vec::new();
        for iv in pair.get_item(1)?.iter()? {
            vars.push(convert_import_var(&iv?)?);
        }
        imports.push((lib, vars));
    }

    let mut deps: Vec<Arc<Var>> = Vec::new();
    for d in obj.getattr("deps")?.iter()? {
        let js: String = d?.getattr("_js_expr")?.extract()?;
        deps.push(Arc::new(Var::new(js)));
    }

    Ok(Some(VarData {
        state,
        field_name,
        imports,
        hooks,
        deps,
        position: None,
        components: Vec::new(),
    }))
}

/// Parse the polymorphic `imports` constructor arg into the Rust shape.
///
/// Accepts `None`, a parsed tuple `((lib, (ImportVar, ...)), ...)`, or a dict
/// `{lib: [ImportVar|str, ...]}` (mirrors `parse_imports`): internal libs are
/// `$`-prefixed, and bare string tags become `ImportVar`s.
fn parse_imports_arg(
    imports: Option<&Bound<'_, PyAny>>,
) -> PyResult<Vec<(String, Vec<ImportVar>)>> {
    let Some(obj) = imports else {
        return Ok(Vec::new());
    };
    if obj.is_none() {
        return Ok(Vec::new());
    }
    let mut out: Vec<(String, Vec<ImportVar>)> = Vec::new();
    // dict {lib: [vars]} or parsed tuple ((lib, (vars,)), ...) — both iterate as
    // (lib, vars) pairs when a dict is turned into .items(); detect dict first.
    let pairs: Vec<(Bound<'_, PyAny>, Bound<'_, PyAny>)> =
        if let Ok(dict) = obj.downcast::<pyo3::types::PyDict>() {
            dict.iter().collect()
        } else {
            let mut v = Vec::new();
            for pair in obj.iter()? {
                let pair = pair?;
                v.push((pair.get_item(0)?, pair.get_item(1)?));
            }
            v
        };
    for (lib, vars) in pairs {
        let lib = normalize_import_lib(&lib.extract::<String>()?);
        let mut ivs = Vec::new();
        // The dict value may be a single ImportVar/str OR a list/tuple/set of
        // them (matches `merge_imports`, which `.append`s a scalar but
        // `.extend`s a sequence).
        let is_seq = vars.downcast::<PyList>().is_ok()
            || vars.downcast::<pyo3::types::PyTuple>().is_ok()
            || vars.downcast::<pyo3::types::PySet>().is_ok();
        let items: Vec<Bound<'_, PyAny>> = if is_seq {
            vars.iter()?.collect::<PyResult<Vec<_>>>()?
        } else {
            vec![vars.clone()]
        };
        for item in items {
            ivs.push(if let Ok(s) = item.extract::<String>() {
                ImportVar::new(s)
            } else {
                convert_import_var(&item)?
            });
        }
        match out.iter().position(|(m, _)| *m == lib) {
            Some(i) => out[i].1.extend(ivs),
            None => out.push((lib, ivs)),
        }
    }
    Ok(out)
}

/// Parse the polymorphic `hooks` arg (str / list / dict) into an ordered,
/// deduped `Vec<String>` (matches `dict.fromkeys(hooks)`).
fn parse_hooks_arg(hooks: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<String>> {
    let Some(obj) = hooks else {
        return Ok(Vec::new());
    };
    if obj.is_none() {
        return Ok(Vec::new());
    }
    let mut out: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    if let Ok(s) = obj.extract::<String>() {
        out.push(s);
        return Ok(out);
    }
    // A hooks dict maps `hook_str -> VarData | None`: each value's own hooks are
    // dependencies that must appear BEFORE the key (depth-first), matching
    // `VarData`'s nested-hook flattening. A list/tuple is just hook strings.
    if let Ok(dict) = obj.downcast::<pyo3::types::PyDict>() {
        for (k, v) in dict.iter() {
            if !v.is_none() {
                if let Ok(nested) = v.getattr("hooks") {
                    for h in nested.iter()? {
                        let h: String = h?.extract()?;
                        if seen.insert(h.clone()) {
                            out.push(h);
                        }
                    }
                }
            }
            let key: String = k.extract()?;
            if seen.insert(key.clone()) {
                out.push(key);
            }
        }
    } else {
        for h in obj.iter()? {
            let h: String = h?.extract()?;
            if seen.insert(h.clone()) {
                out.push(h);
            }
        }
    }
    Ok(out)
}

/// Parse the `deps` arg (list of vars) into bare-expression `Var`s.
fn parse_deps_arg(deps: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<Arc<Var>>> {
    let Some(obj) = deps else {
        return Ok(Vec::new());
    };
    if obj.is_none() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    for d in obj.iter()? {
        let js: String = d?.getattr("_js_expr")?.extract()?;
        out.push(Arc::new(Var::new(js)));
    }
    Ok(out)
}

/// Convert a Python `ImportVar` into the Rust struct.
///
/// Args:
///     iv: The Python `ImportVar`.
///
/// Returns:
///     The converted `ImportVar`.
fn convert_import_var(iv: &Bound<'_, PyAny>) -> PyResult<ImportVar> {
    Ok(ImportVar {
        tag: iv.getattr("tag")?.extract().unwrap_or(None),
        is_default: iv.getattr("is_default")?.extract().unwrap_or(false),
        alias: iv.getattr("alias")?.extract().unwrap_or(None),
        install: iv.getattr("install")?.extract().unwrap_or(true),
        render: iv.getattr("render")?.extract().unwrap_or(true),
        package_path: iv
            .getattr("package_path")
            .and_then(|p| p.extract())
            .unwrap_or_else(|_| "/".to_owned()),
    })
}

/// Render an f64 as JS source. Integral floats keep a trailing `.0` only when
/// Python's `repr` would; for now this matches the corpus (`1.5` -> `1.5`).
fn render_js_float(f: f64) -> String {
    // Rust's f64 Display already yields the shortest round-trip form ("1.5").
    format!("{f}")
}

/// A Rust-backed `VarData` exposed to Python with the read surface the
/// framework consumes (`state`, `field_name`, `hooks`, `deps`, `imports`).
#[pyclass(frozen, name = "RustVarData", module = "reflex_compiler_rust._native")]
pub struct PyVarData {
    inner: VarData,
}

#[pymethods]
impl PyVarData {
    /// Drop-in for the Python `VarData(state, field_name, imports, hooks, deps,
    /// position, components)` constructor. Accepts the polymorphic `imports`
    /// (dict or parsed tuple) and `hooks` (str / list / dict) forms, applying
    /// `$`-prefix normalization to internal libs (mirrors `parse_imports`).
    #[new]
    #[pyo3(signature = (
        state = String::new(),
        field_name = String::new(),
        imports = None,
        hooks = None,
        deps = None,
        position = None,
        components = None,
    ))]
    fn new(
        state: String,
        field_name: String,
        imports: Option<Bound<'_, PyAny>>,
        hooks: Option<Bound<'_, PyAny>>,
        deps: Option<Bound<'_, PyAny>>,
        position: Option<Bound<'_, PyAny>>,
        components: Option<Bound<'_, PyAny>>,
    ) -> PyResult<PyVarData> {
        let _ = (position, components);
        Ok(PyVarData {
            inner: VarData {
                state,
                field_name,
                imports: parse_imports_arg(imports.as_ref())?,
                hooks: parse_hooks_arg(hooks.as_ref())?,
                deps: parse_deps_arg(deps.as_ref())?,
                position: None,
                components: Vec::new(),
            },
        })
    }

    /// Merge any number of `VarData` (or `None`) into one — the drop-in for the
    /// Python `VarData.merge(*all)` staticmethod.
    #[staticmethod]
    #[pyo3(signature = (*all))]
    fn merge(all: Vec<Bound<'_, PyAny>>) -> PyResult<Option<PyVarData>> {
        let mut datas: Vec<VarData> = Vec::new();
        for obj in &all {
            if let Some(vd) = convert_var_data(obj)? {
                datas.push(vd);
            }
        }
        Ok(VarData::merge(datas.iter().map(Some))
            .ok()
            .flatten()
            .map(|inner| PyVarData { inner }))
    }

    /// Build the var_data for a state field — the reactive leaf's
    /// `useContext` hook + StateContexts/useContext imports. Drop-in for
    /// `VarData.from_state`.
    #[staticmethod]
    #[pyo3(signature = (state, field_name = String::new()))]
    fn from_state(state: Bound<'_, PyAny>, field_name: String) -> PyResult<PyVarData> {
        let state_name = match state.extract::<String>() {
            Ok(s) => s,
            Err(_) => state.call_method0("get_full_name")?.extract()?,
        };
        let mangled = state_name.replace('.', "__");
        let hook = format!("const {mangled} = useContext(StateContexts.{mangled})");
        Ok(PyVarData {
            inner: VarData {
                state: state_name,
                field_name,
                imports: vec![
                    (
                        "$/utils/context".to_owned(),
                        vec![ImportVar::new("StateContexts")],
                    ),
                    ("react".to_owned(), vec![ImportVar::new("useContext")]),
                ],
                hooks: vec![hook],
                deps: Vec::new(),
                position: None,
                components: Vec::new(),
            },
        })
    }

    /// Imports as a mutable dict `{lib: [ImportVar, ...]}` (drop-in for
    /// `old_school_imports`).
    fn old_school_imports<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
        let dict = pyo3::types::PyDict::new_bound(py);
        for (lib, vars) in &self.inner.imports {
            let mut ivs: Vec<Bound<'py, PyAny>> = Vec::with_capacity(vars.len());
            for iv in vars {
                ivs.push(Bound::new(py, PyImportVar { inner: iv.clone() })?.into_any());
            }
            dict.set_item(lib, pyo3::types::PyList::new_bound(py, ivs))?;
        }
        Ok(dict)
    }

    #[getter]
    fn position(&self, py: Python<'_>) -> Py<PyAny> {
        py.None()
    }

    #[getter]
    fn components(&self) -> Vec<PyObject> {
        Vec::new()
    }

    fn __repr__(&self) -> String {
        format!(
            "VarData(state={:?}, field_name={:?}, hooks={} imports={})",
            self.inner.state,
            self.inner.field_name,
            self.inner.hooks.len(),
            self.inner.imports.len()
        )
    }

    /// Pickle support: reconstruct via the constructor from (state, field_name,
    /// imports, hooks, deps).
    fn __reduce__(&self, py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        let cls = PyVarData::type_object_bound(py).into_any().unbind();
        let args = (
            self.inner.state.clone(),
            self.inner.field_name.clone(),
            self.imports(py)?,
            self.hooks(py),
            self.deps(py)?,
        );
        Ok((cls, args.into_py(py)))
    }

    /// Truthiness — `False` when every field is empty (matches `__bool__`).
    fn __bool__(&self) -> bool {
        !self.inner.is_empty()
    }

    fn __hash__(&self) -> u64 {
        use std::hash::{Hash, Hasher};
        let mut h = std::collections::hash_map::DefaultHasher::new();
        self.inner.state.hash(&mut h);
        self.inner.field_name.hash(&mut h);
        self.inner.hooks.hash(&mut h);
        h.finish()
    }

    fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
        other
            .downcast::<PyVarData>()
            .map(|o| o.borrow().inner == self.inner)
            .unwrap_or(false)
    }

    #[getter]
    fn state(&self) -> &str {
        &self.inner.state
    }

    #[getter]
    fn field_name(&self) -> &str {
        &self.inner.field_name
    }

    /// Hooks as a tuple of strings (matches `VarData.hooks: tuple[str, ...]`).
    #[getter]
    fn hooks<'py>(&self, py: Python<'py>) -> Bound<'py, pyo3::types::PyTuple> {
        pyo3::types::PyTuple::new_bound(py, &self.inner.hooks)
    }

    /// Imports as the `ParsedImportTuple` shape `((lib, (ImportVar, ...)), ...)`
    /// — a **tuple** of tuples (the framework does `isinstance(imports, tuple)`),
    /// duplicates preserved.
    #[getter]
    fn imports<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyTuple>> {
        let mut modules: Vec<Bound<'py, pyo3::types::PyTuple>> =
            Vec::with_capacity(self.inner.imports.len());
        for (lib, vars) in &self.inner.imports {
            let mut ivs: Vec<Bound<'py, PyAny>> = Vec::with_capacity(vars.len());
            for iv in vars {
                ivs.push(Bound::new(py, PyImportVar { inner: iv.clone() })?.into_any());
            }
            let inner = pyo3::types::PyTuple::new_bound(py, ivs);
            let pair: [Bound<'py, PyAny>; 2] =
                [PyString::new_bound(py, lib).into_any(), inner.into_any()];
            modules.push(pyo3::types::PyTuple::new_bound(py, pair));
        }
        Ok(pyo3::types::PyTuple::new_bound(py, modules))
    }

    /// Deps as a tuple of bare `RustVar`s (the framework reads only `_js_expr`).
    #[getter]
    fn deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyTuple>> {
        let mut out: Vec<Bound<'py, PyAny>> = Vec::with_capacity(self.inner.deps.len());
        for d in &self.inner.deps {
            let v = RustVar {
                js_expr: d.js_expr().to_owned(),
                var_type: py.None(),
                var_data: None,
            };
            out.push(Bound::new(py, v)?.into_any());
        }
        Ok(pyo3::types::PyTuple::new_bound(py, out))
    }
}

/// A Rust-backed `ImportVar` exposed to Python. The framework reads `tag`
/// (plus the rendering attributes), so they are surfaced as getters.
#[pyclass(
    frozen,
    name = "RustImportVar",
    module = "reflex_compiler_rust._native"
)]
pub struct PyImportVar {
    inner: ImportVar,
}

#[pymethods]
impl PyImportVar {
    /// Drop-in for the Python `ImportVar(tag, is_default, alias, install,
    /// render, package_path)` constructor.
    #[new]
    #[pyo3(signature = (
        tag = None,
        is_default = false,
        alias = None,
        install = true,
        render = true,
        package_path = "/".to_owned(),
    ))]
    fn new(
        tag: Option<String>,
        is_default: bool,
        alias: Option<String>,
        install: bool,
        render: bool,
        package_path: String,
    ) -> PyImportVar {
        PyImportVar {
            inner: ImportVar {
                tag,
                is_default,
                alias,
                install,
                render,
                package_path,
            },
        }
    }

    /// Field-wise equality against any `ImportVar`-like object (Python
    /// `ImportVar` or another `RustImportVar`). Python's dataclass `__eq__`
    /// returns `NotImplemented` for a foreign type, so this reflected compare is
    /// what makes `ImportVar(...) in [rust_import_var, ...]` work.
    fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
        let i = &self.inner;
        let s =
            |n: &str| -> Option<String> { other.getattr(n).ok().and_then(|v| v.extract().ok()) };
        let b = |n: &str, d: bool| {
            other
                .getattr(n)
                .ok()
                .and_then(|v| v.extract().ok())
                .unwrap_or(d)
        };
        i.tag == s("tag")
            && i.alias
                == other
                    .getattr("alias")
                    .ok()
                    .and_then(|v| v.extract::<Option<String>>().ok())
                    .flatten()
            && i.is_default == b("is_default", !i.is_default)
            && i.install == b("install", !i.install)
            && i.render == b("render", !i.render)
            && Some(i.package_path.clone()) == s("package_path")
    }

    fn __hash__(&self) -> u64 {
        use std::hash::{Hash, Hasher};
        let mut h = std::collections::hash_map::DefaultHasher::new();
        self.inner.hash(&mut h);
        h.finish()
    }

    /// Pickle support: reconstruct via the constructor.
    fn __reduce__(&self, py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        let cls = PyImportVar::type_object_bound(py).into_any().unbind();
        let i = &self.inner;
        let args = (
            i.tag.clone(),
            i.is_default,
            i.alias.clone(),
            i.install,
            i.render,
            i.package_path.clone(),
        );
        Ok((cls, args.into_py(py)))
    }

    /// The display name used in `import { name } from "lib"` (drop-in for
    /// `ImportVar.name`).
    #[getter]
    fn name(&self) -> String {
        self.inner.name()
    }

    #[getter]
    fn tag(&self) -> Option<String> {
        self.inner.tag.clone()
    }

    #[getter]
    fn is_default(&self) -> bool {
        self.inner.is_default
    }

    #[getter]
    fn alias(&self) -> Option<String> {
        self.inner.alias.clone()
    }

    #[getter]
    fn install(&self) -> bool {
        self.inner.install
    }

    #[getter]
    fn render(&self) -> bool {
        self.inner.render
    }

    #[getter]
    fn package_path(&self) -> &str {
        &self.inner.package_path
    }
}

/// Rust-backed `LiteralVar` — a `Var` (RustVar) that also carries the original
/// Python value it was built from. Mirrors `LiteralVar(Var)`: it **extends**
/// `RustVar` (inheriting `_js_expr` / `_var_type` / `_get_all_var_data` / every
/// operator) and adds `_var_value` plus the `create` dispatch.
#[pyclass(
    extends = RustVar,
    subclass,
    frozen,
    name = "RustLiteralVar",
    module = "reflex_compiler_rust._native"
)]
pub struct RustLiteralVar {
    var_value: Py<PyAny>,
}

#[pymethods]
impl RustLiteralVar {
    /// The original Python value this literal was created from.
    #[getter]
    fn _var_value(&self, py: Python<'_>) -> Py<PyAny> {
        self.var_value.clone_ref(py)
    }

    /// `LiteralVar.create(value, _var_data=None)` — entirely in Rust.
    ///
    /// An existing Var passes through unchanged; a marker-encoded string
    /// decodes into a concat; every other scalar / list / dict becomes a
    /// literal. `_var_data` is merged into the result. Exotic types
    /// (EventChain, serializer-backed, dataclasses) remain on the Python
    /// dispatch and are layered in separately.
    ///
    /// Args:
    ///     _cls: The class object (unused).
    ///     py: The GIL token.
    ///     value: The value to wrap.
    ///     _var_data: Extra var_data to merge in.
    ///
    /// Returns:
    ///     The value itself if already a Var, else a new `RustLiteralVar`.
    #[classmethod]
    #[pyo3(signature = (value, _var_data = None))]
    fn create(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        value: Bound<'_, PyAny>,
        _var_data: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        // An existing Var is returned as-is (matches `LiteralVar.create(Var)`).
        if value.hasattr("_js_expr")? && value.hasattr("_var_type")? {
            return Ok(value.unbind());
        }
        // Underlying RustVar: marker string -> concat, else scalar/list/dict.
        let mut inner = match value.extract::<String>() {
            Ok(s) if s.contains(VAR_OPENING_TAG) => rust_create_string(py, s),
            _ => rust_literal(py, value.clone())?,
        };
        if let Some(vd) = _var_data {
            if let Some(extra) = convert_var_data(&vd)? {
                inner.var_data = VarData::merge([inner.var_data.as_ref(), Some(&extra)])
                    .ok()
                    .flatten();
            }
        }
        let init = pyo3::PyClassInitializer::from(inner).add_subclass(RustLiteralVar {
            var_value: value.unbind(),
        });
        Ok(Py::new(py, init)?.into_any())
    }
}

/// Rust-backed `LiteralEventChainVar` — extends `RustLiteralVar`, mirroring
/// `LiteralEventChainVar(…, LiteralVar, EventChainVar)`. Its `create` renders
/// the chain JS via the Rust assembler (instead of composing a per-event Var
/// tree, which is the ~3 ms Python hotspot) and gathers the chain's var_data.
#[pyclass(
    extends = RustLiteralVar,
    frozen,
    name = "RustLiteralEventChainVar",
    module = "reflex_compiler_rust._native"
)]
pub struct RustLiteralEventChainVar {}

#[pymethods]
impl RustLiteralEventChainVar {
    /// `LiteralEventChainVar.create(value, _var_data=None)` in Rust.
    ///
    /// Args:
    ///     _cls: The class object (unused).
    ///     py: The GIL token.
    ///     value: The `EventChain`.
    ///     _var_data: Extra var_data to merge in.
    ///
    /// Returns:
    ///     A `RustLiteralEventChainVar` whose `_js_expr` is the assembled chain.
    #[classmethod]
    #[pyo3(signature = (value, _var_data = None))]
    fn create(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        value: Bound<'_, PyAny>,
        _var_data: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let js_expr = rust_assemble_event_chain(py, value.clone())?;
        let var_type = value.get_type().into_any().unbind();
        let var_data = gather_event_chain_var_data(py, &value, _var_data.as_ref())?;
        let base = RustVar {
            js_expr,
            var_type,
            var_data,
        };
        let init = pyo3::PyClassInitializer::from(base)
            .add_subclass(RustLiteralVar {
                var_value: value.unbind(),
            })
            .add_subclass(RustLiteralEventChainVar {});
        Ok(Py::new(py, init)?.into_any())
    }
}

/// Public wrapper: gather an event chain's aggregate var_data as a
/// `RustVarData` (or `None`). Lets the Python `LiteralEventChainVar.create`
/// reuse the exact gather without rebuilding the per-event Var tree.
///
/// Args:
///     py: The GIL token.
///     chain: The `EventChain`.
///     _var_data: Extra var_data to merge in.
///
/// Returns:
///     The chain's aggregate `RustVarData`, or `None`.
#[pyfunction]
#[pyo3(signature = (chain, _var_data = None))]
pub fn rust_event_chain_var_data(
    py: Python<'_>,
    chain: Bound<'_, PyAny>,
    _var_data: Option<Bound<'_, PyAny>>,
) -> PyResult<Option<PyVarData>> {
    Ok(gather_event_chain_var_data(py, &chain, _var_data.as_ref())?
        .map(|inner| PyVarData { inner }))
}

/// Gather an event chain's aggregate var_data: the `addEvents` EVENTS
/// imports/hook (from `reflex_base.constants.compiler`) plus the var_data of
/// every Var referenced in the chain's events (handler args + event actions)
/// and the chain-level actions, plus any caller-supplied `extra`.
fn gather_event_chain_var_data(
    py: Python<'_>,
    chain: &Bound<'_, PyAny>,
    extra: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<VarData>> {
    let compiler = py.import_bound("reflex_base.constants.compiler")?;
    let events_imports = compiler.getattr("Imports")?.getattr("EVENTS")?;
    let events_hook: String = compiler.getattr("Hooks")?.getattr("EVENTS")?.extract()?;
    // The `addEvents` invocation carries this EVENTS var_data, and the chain
    // includes it ONCE PER EVENT statement (plus once more for the
    // apply-event-actions wrapper when chain-level actions exist).
    let events_vd = VarData {
        imports: parse_imports_arg(Some(&events_imports))?,
        hooks: vec![events_hook],
        ..VarData::default()
    };
    let mut parts: Vec<VarData> = Vec::new();

    let collect = |obj: &Bound<'_, PyAny>, parts: &mut Vec<VarData>| -> PyResult<()> {
        if let Ok(true) = obj.hasattr("_get_all_var_data") {
            if let Some(vd) = convert_var_data(&obj.call_method0("_get_all_var_data")?)? {
                parts.push(vd);
            }
        }
        Ok(())
    };

    // The invocation an EventSpec is wrapped in: the default `addEvents`
    // carries the EVENTS var_data; a custom invocation carries its own (which
    // may be empty, e.g. FunctionStringVar("")).
    let invocation = chain.getattr("invocation")?;
    let invocation_vd: Option<VarData> = if invocation.is_none() {
        Some(events_vd.clone())
    } else {
        convert_var_data(&invocation.call_method0("_get_all_var_data")?)?
    };

    let events: Vec<Bound<'_, PyAny>> =
        chain.getattr("events")?.iter()?.collect::<PyResult<_>>()?;
    // No events still emits a single invocation.
    if events.is_empty() {
        if let Some(vd) = &invocation_vd {
            parts.push(vd.clone());
        }
    }
    for es in &events {
        // A FunctionVar event (no `handler`) renders as `event.call(...)` and
        // contributes only its own var_data — no invocation. An EventSpec is
        // wrapped in the invocation, so it carries the invocation's var_data
        // plus its args' and actions' var_data.
        if !es.hasattr("handler")? {
            collect(es, &mut parts)?;
            continue;
        }
        if let Some(vd) = &invocation_vd {
            parts.push(vd.clone());
        }
        for arg in es.getattr("args")?.iter()? {
            let arg = arg?;
            collect(&arg.get_item(0)?, &mut parts)?;
            collect(&arg.get_item(1)?, &mut parts)?;
        }
        for v in es
            .getattr("event_actions")?
            .downcast::<pyo3::types::PyDict>()?
            .values()
        {
            collect(&v, &mut parts)?;
        }
    }
    let chain_actions = chain.getattr("event_actions")?;
    let chain_actions = chain_actions.downcast::<pyo3::types::PyDict>()?;
    if !chain_actions.is_empty() {
        parts.push(events_vd.clone());
        for v in chain_actions.values() {
            collect(&v, &mut parts)?;
        }
    }
    if let Some(e) = extra {
        if let Some(vd) = convert_var_data(e)? {
            parts.push(vd);
        }
    }
    Ok(VarData::merge(parts.iter().map(Some)).ok().flatten())
}

/// One segment of a decoded marker string: a literal chunk or a referenced var.
enum StrPart {
    Lit(String),
    Var(String, Option<VarData>),
}

/// Build a string var from a (possibly marker-encoded) f-string value.
///
/// Mirrors `LiteralStringVar.create`: a plain string becomes a string literal;
/// a marker-encoded string is decoded into alternating literal chunks and
/// referenced vars (looked up in the registry) and assembled into a
/// `ConcatVarOperation` — `(p0+p1+...)` with literals rendered as JS strings
/// and vars as their js_expr. var_data is a single (plain) merge of the parts.
///
/// Args:
///     py: The GIL token.
///     value: The raw f-string value (with embedded `<reflex.Var>` markers).
///
/// Returns:
///     A `RustVar` of type `str`.
#[pyfunction]
pub fn rust_create_string(py: Python<'_>, value: String) -> RustVar {
    let str_ty = PyString::type_object_bound(py).into_any().unbind();
    if !value.contains(VAR_OPENING_TAG) {
        return RustVar {
            js_expr: render_js_string(&value),
            var_type: str_ty,
            var_data: None,
        };
    }

    let parts = decode_marker_parts(&value);
    let filtered: Vec<StrPart> = parts
        .into_iter()
        .filter(|p| !matches!(p, StrPart::Lit(s) if s.is_empty()))
        .collect();

    // Single var → that var (as a string); single literal → string literal.
    if filtered.len() == 1 {
        return match &filtered[0] {
            StrPart::Lit(s) => RustVar {
                js_expr: render_js_string(s),
                var_type: str_ty,
                var_data: None,
            },
            StrPart::Var(js, data) => RustVar {
                js_expr: js.clone(),
                var_type: str_ty,
                var_data: var_op_plain(&[data]),
            },
        };
    }

    let rendered: Vec<String> = filtered
        .iter()
        .map(|p| match p {
            StrPart::Lit(s) => render_js_string(s),
            StrPart::Var(js, _) => js.clone(),
        })
        .collect();
    let datas: Vec<&Option<VarData>> = filtered
        .iter()
        .map(|p| match p {
            StrPart::Lit(_) => &NONE_VAR_DATA,
            StrPart::Var(_, data) => data,
        })
        .collect();
    RustVar {
        js_expr: format!("({})", rendered.join("+")),
        var_type: str_ty,
        var_data: var_op_plain(&datas),
    }
}

/// A stable `None` var_data to borrow for literal parts in the concat merge.
static NONE_VAR_DATA: Option<VarData> = None;

/// Decode `<reflex.Var>` markers in place: strip the tags (keeping the inline
/// js_expr that follows each) and merge the referenced vars' var_data.
///
/// Mirrors `_decode_var_immutable` (base.py): unlike `rust_create_string`
/// (which splits into a concat), this just removes the tags and aggregates the
/// embedded var_data — the form `Var.__post_init__` applies to a raw js_expr.
///
/// Returns the cleaned js_expr and the merged var_data of all referenced vars.
fn decode_markers_inline(value: &str) -> (String, Option<VarData>) {
    let reg = var_registry().lock().ok();
    let mut out = String::with_capacity(value.len());
    let mut datas: Vec<VarData> = Vec::new();
    let mut rest = value;
    loop {
        match rest.find(VAR_OPENING_TAG) {
            None => {
                out.push_str(rest);
                break;
            }
            Some(open) => {
                out.push_str(&rest[..open]);
                let after_open = &rest[open + VAR_OPENING_TAG.len()..];
                let Some(close) = after_open.find(VAR_CLOSING_TAG) else {
                    out.push_str(&rest[open..]);
                    break;
                };
                let id: i64 = after_open[..close].parse().unwrap_or(-1);
                if let Some(Some((_js, Some(data)))) = reg.as_ref().map(|r| r.get(&id)) {
                    datas.push(data.clone());
                }
                // Drop the tag; keep everything after the closing tag (the
                // inline js_expr stays in place).
                rest = &after_open[close + VAR_CLOSING_TAG.len()..];
            }
        }
    }
    let merged = VarData::merge(datas.iter().map(Some)).ok().flatten();
    (out, merged)
}

/// Decode a marker string into literal / var parts.
///
/// Replicates Python's `LiteralStringVar.create` scan: each
/// `<reflex.Var>{id}</reflex.Var>` is replaced by the registered var, and the
/// var's js_expr (which `__format__` appended after the closing tag) is skipped.
fn decode_marker_parts(value: &str) -> Vec<StrPart> {
    let mut parts = Vec::new();
    let mut rest = value;
    let reg = var_registry().lock().ok();
    loop {
        match rest.find(VAR_OPENING_TAG) {
            None => {
                if !rest.is_empty() {
                    parts.push(StrPart::Lit(rest.to_owned()));
                }
                break;
            }
            Some(open) => {
                if open > 0 {
                    parts.push(StrPart::Lit(rest[..open].to_owned()));
                }
                let after_open = &rest[open + VAR_OPENING_TAG.len()..];
                let Some(close) = after_open.find(VAR_CLOSING_TAG) else {
                    parts.push(StrPart::Lit(rest.to_owned()));
                    break;
                };
                let id: i64 = after_open[..close].parse().unwrap_or(-1);
                let (js, data) = reg
                    .as_ref()
                    .and_then(|r| r.get(&id).cloned())
                    .unwrap_or_default();
                parts.push(StrPart::Var(js.clone(), data));
                // Skip the closing tag and the js_expr that follows it.
                let after_close = &after_open[close + VAR_CLOSING_TAG.len()..];
                rest = after_close.strip_prefix(js.as_str()).unwrap_or(after_close);
            }
        }
    }
    parts
}

/// Render one event arg/action value to JS (mirrors `_render_event_value`).
///
/// A Var contributes its cached `_js_expr`; `True`/`False` map to
/// `true`/`false`; any other literal goes through the literal renderer (with a
/// fallback to Python `LiteralVar.create` for exotic types).
fn render_event_value(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(js) = value.getattr("_js_expr") {
        return Ok(js.str()?.to_string());
    }
    if value.is_instance_of::<PyBool>() {
        return Ok(if value.extract::<bool>()? {
            "true"
        } else {
            "false"
        }
        .to_owned());
    }
    if let Ok(s) = render_literal_js(value) {
        return Ok(s);
    }
    // Exotic value (custom serializer etc.) — defer to the Python literal path.
    let lv = py.import_bound("reflex.vars")?.getattr("LiteralVar")?;
    Ok(lv
        .call_method1("create", (value,))?
        .getattr("_js_expr")?
        .str()?
        .to_string())
}

/// Render an emit-style JS object literal `({ ["k"] : v, ... })` (mirrors
/// `_js_object`): empty -> `({  })`.
fn js_object(pairs: &[(String, String)]) -> String {
    if pairs.is_empty() {
        return "({  })".to_owned();
    }
    let inner: Vec<String> = pairs
        .iter()
        .map(|(k, v)| format!("[\"{k}\"] : {v}"))
        .collect();
    format!("({{ {} }})", inner.join(", "))
}

/// The ReflexEvent name for a handler (mirrors `_event_handler_name`):
/// `state_full_name.fn_name` for state handlers, else `fn.__qualname__`.
fn event_handler_name(handler: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(sfn) = handler.getattr("state_full_name") {
        let sfn: String = sfn.extract().unwrap_or_default();
        if !sfn.is_empty() {
            let fn_name: String = handler.getattr("fn")?.getattr("__name__")?.extract()?;
            return Ok(format!("{sfn}.{fn_name}"));
        }
    }
    handler.getattr("fn")?.getattr("__qualname__")?.extract()
}

/// Lambda arg names for a trigger's `args_spec` (`e` -> `_e`), via
/// `inspect.signature` (mirrors `_arg_names`). An `args_spec` that is a
/// sequence of spec functions uses its first element (matches the Python
/// `args_spec[0] if isinstance(..., Sequence)`); a `str` is not a sequence here.
fn arg_names(py: Python<'_>, args_spec: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    let spec = if (args_spec.is_instance_of::<pyo3::types::PyList>()
        || args_spec.is_instance_of::<pyo3::types::PyTuple>())
        && args_spec.len().map(|n| n > 0).unwrap_or(false)
    {
        args_spec.get_item(0)?
    } else {
        args_spec.clone()
    };
    let sig = py
        .import_bound("inspect")?
        .call_method1("signature", (spec,))?;
    let mut names = Vec::new();
    for key in sig.getattr("parameters")?.call_method0("keys")?.iter()? {
        names.push(format!("_{}", key?.extract::<String>()?));
    }
    Ok(names)
}

/// Assemble an `EventChain`'s JS, byte-identical to
/// `LiteralVar.create(chain)._js_expr` (mirrors `_assemble_event_chain`).
///
/// Reads the raw chain pieces (handler names, each arg's cached `_js_expr`,
/// event_actions, arg-names) and string-assembles the
/// `(_e) => addEvents([ReflexEvent(...)], [_e], …)` form entirely in Rust.
///
/// Args:
///     py: The GIL token.
///     chain: The `EventChain`.
///
/// Returns:
///     The rendered event-chain JS.
#[pyfunction]
pub fn rust_assemble_event_chain(py: Python<'_>, chain: Bound<'_, PyAny>) -> PyResult<String> {
    let names = arg_names(py, &chain.getattr("args_spec")?)?;
    let (arrow_args, arg_def_expr, call_args) = arg_forms(&names);

    // The function each EventSpec is wrapped in: default `addEvents`, or a
    // custom invocation's js (e.g. forms' `submit_it`).
    let invocation = chain.getattr("invocation")?;
    let invocation_js = if invocation.is_none() {
        "addEvents".to_owned()
    } else {
        invocation.getattr("_js_expr")?.str()?.to_string()
    };

    let mut chain_ea = Vec::new();
    for (k, v) in chain
        .getattr("event_actions")?
        .downcast::<pyo3::types::PyDict>()?
        .iter()
    {
        chain_ea.push((k.extract::<String>()?, render_event_value(py, &v)?));
    }

    let events: Vec<Bound<'_, PyAny>> =
        chain.getattr("events")?.iter()?.collect::<PyResult<_>>()?;

    let mut statements: Vec<String> = Vec::new();
    if events.is_empty() {
        statements.push(format!("({invocation_js}([], {arg_def_expr}, ({{  }})))"));
    }
    for es in &events {
        // A FunctionVar event (no `handler`) renders as a direct call
        // `(fn(call_args))`; an EventSpec renders the addEvents(ReflexEvent) form
        // with an ALWAYS-empty 3rd arg (chain actions go in the wrapper).
        if !es.hasattr("handler")? {
            let func = es.getattr("_js_expr")?.str()?.to_string();
            statements.push(render_function_event(&func, &call_args));
            continue;
        }
        let name = event_handler_name(&es.getattr("handler")?)?;
        let mut arg_pairs = Vec::new();
        for a in es.getattr("args")?.iter()? {
            let a = a?;
            let key: String = a.get_item(0)?.getattr("_js_expr")?.str()?.to_string();
            arg_pairs.push((key, render_event_value(py, &a.get_item(1)?)?));
        }
        let mut ea_pairs = Vec::new();
        for (k, v) in es
            .getattr("event_actions")?
            .downcast::<pyo3::types::PyDict>()?
            .iter()
        {
            ea_pairs.push((k.extract::<String>()?, render_event_value(py, &v)?));
        }
        let rei = format!(
            "(ReflexEvent(\"{name}\", {}, {}))",
            js_object(&arg_pairs),
            js_object(&ea_pairs)
        );
        statements.push(format!(
            "({invocation_js}([{rei}], {arg_def_expr}, ({{  }})))"
        ));
    }

    Ok(finalize_chain(
        &arrow_args,
        &statements,
        &chain_ea,
        &call_args,
    ))
}

/// The pure string-assembly core shared by both event-chain entrypoints.
///
/// Takes already-extracted primitives — arg names, chain-level event actions,
/// and per-event `(name, args, event_actions)` — and builds the
/// `(_e) => addEvents([ReflexEvent(...)], [_e], …)` form. No PyO3 reads.
type EventTriple = (String, Vec<(String, String)>, Vec<(String, String)>);

fn assemble_chain_js(
    arg_names: &[String],
    chain_ea: &[(String, String)],
    events: &[EventTriple],
) -> String {
    let (arrow_args, arg_def_expr, call_args) = arg_forms(arg_names);
    // One addEvents per event (3rd arg ALWAYS empty — chain actions live in the
    // applyEventActions wrapper). No events still emits a single addEvents([]).
    let statements: Vec<String> = if events.is_empty() {
        vec![format!("(addEvents([], {arg_def_expr}, ({{  }})))")]
    } else {
        events
            .iter()
            .map(|(name, args, ea)| {
                let rei = format!(
                    "(ReflexEvent(\"{name}\", {}, {}))",
                    js_object(args),
                    js_object(ea)
                );
                format!("(addEvents([{rei}], {arg_def_expr}, ({{  }})))")
            })
            .collect()
    };
    finalize_chain(&arrow_args, &statements, chain_ea, &call_args)
}

/// Whether an expression begins with an inline arrow function (`x => …`,
/// `(…) => …`, optionally `async`). Mirrors `_starts_with_arrow_function`.
fn starts_with_arrow_function(expr: &str) -> bool {
    if !expr.contains("=>") {
        return false;
    }
    let mut expr = expr.trim_start();
    if let Some(rem) = expr.strip_prefix("async") {
        if rem.starts_with(char::is_whitespace) {
            expr = rem.trim_start();
        }
    }
    let Some(first) = expr.chars().next() else {
        return false;
    };
    let ident = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '$';
    if first.is_ascii_alphabetic() || first == '_' || first == '$' {
        let end = expr.find(|c: char| !ident(c)).unwrap_or(expr.len());
        return expr[end..].trim_start().starts_with("=>");
    }
    if !expr.starts_with('(') {
        return false;
    }
    let mut depth = 0i32;
    let mut sd: Option<char> = None;
    let mut esc = false;
    for (i, ch) in expr.char_indices() {
        if let Some(d) = sd {
            if esc {
                esc = false;
            } else if ch == '\\' {
                esc = true;
            } else if ch == d {
                sd = None;
            }
            continue;
        }
        match ch {
            '\'' | '"' | '`' => sd = Some(ch),
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    return expr[i + ch.len_utf8()..].trim_start().starts_with("=>");
                }
            }
            _ => {}
        }
    }
    false
}

/// Whether `text` is wrapped in a single matching pair of parens (`((a))` /
/// `(a)` -> true; `(a) + (b)` -> false). Mirrors `format.is_wrapped(_, "(")`.
fn is_wrapped_parens(text: &str) -> bool {
    if !(text.starts_with('(') && text.ends_with(')')) {
        return false;
    }
    let chars: Vec<char> = text.chars().collect();
    let mut depth = 0i32;
    for &ch in &chars[..chars.len() - 1] {
        if ch == '(' {
            depth += 1;
        } else if ch == ')' {
            depth -= 1;
        }
        if depth == 0 {
            return false;
        }
    }
    true
}

/// Render a FunctionVar event's call `(func(args))`, wrapping an inline arrow
/// `func` in parens first (matches `VarOperationCall._cached_var_name`).
fn render_function_event(func: &str, call_args: &str) -> String {
    let func_part = if starts_with_arrow_function(func) && !is_wrapped_parens(func) {
        format!("({func})")
    } else {
        func.to_owned()
    };
    format!("({func_part}({call_args}))")
}

/// Argument forms for an event-chain trigger from its lambda arg names:
/// `(arrow_args, arg_def_expr, call_args)`. With params `e` -> `_e`:
/// `("_e", "[_e]", "_e")`; with none: `("...args", "args", "...args")`.
fn arg_forms(names: &[String]) -> (String, String, String) {
    if names.is_empty() {
        (
            "...args".to_owned(),
            "args".to_owned(),
            "...args".to_owned(),
        )
    } else {
        let csv = names.join(", ");
        (csv.clone(), format!("[{csv}]"), csv)
    }
}

/// Wrap statements into the final `((arrow_args) => body)`. With chain-level
/// event actions, the statement block is wrapped in
/// `applyEventActions((() => {block}), {actions}, call_args)`; otherwise a
/// single statement is the body directly and multiple form a `{...}` block.
fn finalize_chain(
    arrow_args: &str,
    statements: &[String],
    chain_ea: &[(String, String)],
    call_args: &str,
) -> String {
    let block = || -> String {
        format!(
            "{{{}}}",
            statements
                .iter()
                .map(|s| format!("{s};"))
                .collect::<String>()
        )
    };
    let body = if chain_ea.is_empty() {
        if statements.len() == 1 {
            statements[0].clone()
        } else {
            block()
        }
    } else {
        format!(
            "(applyEventActions((() => {}), {}, {call_args}))",
            block(),
            js_object(chain_ea)
        )
    };
    format!("(({arrow_args}) => {body})")
}

/// Assemble an event chain from a **pre-gathered primitive bundle** — the
/// one-FFI-crossing path. Python gathers the raw chain (handler names, each
/// arg's `_js_expr`, rendered action values, arg-names) in a single native
/// pass and ships it here as plain tuples of strings; Rust does only the
/// string assembly, with zero per-attribute PyO3 crossings.
///
/// Args:
///     arg_names: The lambda arg names (e.g. `["_e"]`).
///     chain_ea: Chain-level event actions as `(key, value_js)`.
///     events: Per-event `(name, args, event_actions)` where args/actions are
///         `(key, value_js)` lists.
///
/// Returns:
///     The rendered event-chain JS.
#[pyfunction]
pub fn rust_assemble_event_chain_bundle(
    arg_names: Vec<String>,
    chain_ea: Vec<(String, String)>,
    events: Vec<EventTriple>,
) -> String {
    assemble_chain_js(&arg_names, &chain_ea, &events)
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
    m.add_class::<RustLiteralVar>()?;
    m.add_class::<RustLiteralEventChainVar>()?;
    m.add_class::<PyVarData>()?;
    m.add_class::<PyImportVar>()?;
    m.add_function(wrap_pyfunction!(rust_literal, m)?)?;
    m.add_function(wrap_pyfunction!(rust_raw_var, m)?)?;
    m.add_function(wrap_pyfunction!(rust_from_python_var, m)?)?;
    m.add_function(wrap_pyfunction!(rust_create_string, m)?)?;
    m.add_function(wrap_pyfunction!(rust_assemble_event_chain, m)?)?;
    m.add_function(wrap_pyfunction!(rust_assemble_event_chain_bundle, m)?)?;
    m.add_function(wrap_pyfunction!(rust_event_chain_var_data, m)?)?;
    Ok(())
}
