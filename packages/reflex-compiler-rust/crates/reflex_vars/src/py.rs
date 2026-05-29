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

use std::sync::Arc;

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyFloat, PyInt, PyList, PyString};
use pyo3::PyTypeInfo;

use crate::var::Var;
use crate::var_data::{ImportVar, VarData};

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

    /// Attribute access on an object var: `{o}?.["name"]`, value type, plain.
    /// Mirrors `ObjectVar.__getattr__`. Underscore names raise `AttributeError`
    /// so internal / dunder lookups fall through to normal resolution rather
    /// than being turned into a bogus item access.
    fn __getattr__(&self, py: Python<'_>, name: String) -> PyResult<RustVar> {
        if name.starts_with('_') {
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
            var_data: None,
        });
    }
    // bool before int — bool is an int subclass in Python.
    if value.is_instance_of::<PyBool>() {
        let b = value.extract::<bool>()?;
        return Ok(RustVar {
            js_expr: if b { "true" } else { "false" }.to_owned(),
            var_type: PyBool::type_object_bound(py).into_any().unbind(),
            var_data: None,
        });
    }
    if value.is_instance_of::<PyInt>() {
        let i = value.extract::<i64>()?;
        return Ok(RustVar {
            js_expr: i.to_string(),
            var_type: PyInt::type_object_bound(py).into_any().unbind(),
            var_data: None,
        });
    }
    if value.is_instance_of::<PyFloat>() {
        let f = value.extract::<f64>()?;
        return Ok(RustVar {
            js_expr: render_js_float(f),
            var_type: PyFloat::type_object_bound(py).into_any().unbind(),
            var_data: None,
        });
    }
    if value.is_instance_of::<PyString>() {
        let s = value.extract::<String>()?;
        return Ok(RustVar {
            js_expr: render_js_string(&s),
            var_type: PyString::type_object_bound(py).into_any().unbind(),
            var_data: None,
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
    #[getter]
    fn state(&self) -> &str {
        &self.inner.state
    }

    #[getter]
    fn field_name(&self) -> &str {
        &self.inner.field_name
    }

    #[getter]
    fn hooks(&self) -> Vec<String> {
        self.inner.hooks.clone()
    }

    /// Imports as `[(lib, [ImportVar, ...]), ...]` — duplicates preserved,
    /// matching the Python `VarData.imports` shape.
    #[getter]
    fn imports(&self) -> Vec<(String, Vec<PyImportVar>)> {
        self.inner
            .imports
            .iter()
            .map(|(lib, vars)| {
                (
                    lib.clone(),
                    vars.iter()
                        .map(|iv| PyImportVar { inner: iv.clone() })
                        .collect(),
                )
            })
            .collect()
    }

    /// Deps as bare `RustVar`s (the framework reads only their `_js_expr`).
    #[getter]
    fn deps(&self, py: Python<'_>) -> Vec<RustVar> {
        self.inner
            .deps
            .iter()
            .map(|d| RustVar {
                js_expr: d.js_expr().to_owned(),
                var_type: py.None(),
                var_data: None,
            })
            .collect()
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

/// Register the Var bindings into the `_native` module.
///
/// Args:
///     m: The parent module to register into.
///
/// Returns:
///     `Ok(())` on success.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustVar>()?;
    m.add_class::<PyVarData>()?;
    m.add_class::<PyImportVar>()?;
    m.add_function(wrap_pyfunction!(rust_literal, m)?)?;
    m.add_function(wrap_pyfunction!(rust_raw_var, m)?)?;
    m.add_function(wrap_pyfunction!(rust_from_python_var, m)?)?;
    Ok(())
}
