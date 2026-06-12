//! push_node v0 — the mirror's Rust fast lane (plan §4a-bis).
//!
//! Handles the dominant construction shape only: every kwarg is a schema
//! PROP and every value is a native Var or an exact-type literal. Anything
//! else returns `None` and the Python mirror (`_arena_mirror_kwargs`)
//! handles the call unchanged. Literal wrapping calls the same
//! `RustLiteralVar::create` entry the Python dispatch calls, so the
//! produced Vars are identical by construction.

use pyo3::prelude::*;
use pyo3::PyTypeInfo;
use pyo3::sync::GILProtected;
use pyo3::types::{
    PyBool, PyDict, PyFloat, PyInt, PyList, PySet, PyString, PyTuple, PyType,
};
use reflex_vars::{RustLiteralVar, RustVar};
use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::OnceLock;

struct MirrorClass {
    /// Holds the class so its id stays claimed for the registry's lifetime.
    class_ref: Py<PyAny>,
    /// `(interned name, is_var, Var-valued class default)` in `get_props`
    /// order — the order the `_vars_cache` tuple must follow.
    props: Vec<(Py<PyString>, bool, Option<Py<PyAny>>)>,
    /// kwarg name → index into `props`.
    index: HashMap<String, usize>,
}

fn registry() -> &'static GILProtected<RefCell<HashMap<usize, MirrorClass>>> {
    static R: OnceLock<GILProtected<RefCell<HashMap<usize, MirrorClass>>>> = OnceLock::new();
    R.get_or_init(|| GILProtected::new(RefCell::new(HashMap::new())))
}

/// Register a Component class for the fast lane. Called once per class by
/// `Component._arena_create_eligible` with the schema's prop list (in
/// `get_props` order, with the Var-typed flag) and the Var-valued
/// class-level prop defaults.
#[pyfunction]
pub fn register_mirror_class(
    py: Python<'_>,
    cls: Bound<'_, PyAny>,
    props: Vec<(String, bool)>,
    default_vars: Bound<'_, PyDict>,
) -> PyResult<()> {
    let mut index = HashMap::with_capacity(props.len());
    let mut plist = Vec::with_capacity(props.len());
    for (i, (name, is_var)) in props.into_iter().enumerate() {
        let default = default_vars.get_item(&name)?.map(Bound::unbind);
        index.insert(name.clone(), i);
        plist.push((PyString::intern_bound(py, &name).unbind(), is_var, default));
    }
    registry().get(py).borrow_mut().insert(
        cls.as_ptr() as usize,
        MirrorClass {
            class_ref: cls.unbind(),
            props: plist,
            index,
        },
    );
    Ok(())
}

/// Whether `value` is one of the exact types the Python literal dispatch
/// routes to `RustLiteralVar.create` (vars/base.py:1426), restricted to the
/// types checkable without imports (Decimal/datetime fall back to Python).
fn literal_eligible(value: &Bound<'_, PyAny>) -> bool {
    value.is_none()
        || value.downcast_exact::<PyBool>().is_ok()
        || value.downcast_exact::<PyInt>().is_ok()
        || value.downcast_exact::<PyFloat>().is_ok()
        || value.downcast_exact::<PyString>().is_ok()
        || value.downcast_exact::<PyList>().is_ok()
        || value.downcast_exact::<PyDict>().is_ok()
        || value.downcast_exact::<PyTuple>().is_ok()
        || value.downcast_exact::<PySet>().is_ok()
}

/// The fast lane: build the mirror dict and `_vars_cache` tuple for a
/// props-only call. Returns `None` (Python mirror handles it) when the
/// class is unregistered, any kwarg isn't a schema prop, or a Var-typed
/// prop's value is neither a native Var nor an eligible exact-type literal.
#[pyfunction]
pub fn mirror_props<'py>(
    py: Python<'py>,
    cls: &Bound<'py, PyAny>,
    props: &Bound<'py, PyDict>,
) -> PyResult<Option<(Bound<'py, PyDict>, Bound<'py, PyTuple>)>> {
    let reg = registry().get(py).borrow();
    let Some(info) = reg.get(&(cls.as_ptr() as usize)) else {
        return Ok(None);
    };
    if !info.class_ref.bind(py).is(cls) {
        return Ok(None);
    }
    let mirror = PyDict::new_bound(py);
    let mut var_slots: Vec<Option<Bound<'py, PyAny>>> = vec![None; info.props.len()];
    let mut set_flags: Vec<bool> = vec![false; info.props.len()];
    let lit_cls: OnceLock<Bound<'py, PyType>> = OnceLock::new();
    for (key, value) in props.iter() {
        let Ok(name) = key.downcast::<PyString>() else {
            return Ok(None);
        };
        let Some(&i) = info.index.get(name.to_str()?) else {
            return Ok(None);
        };
        let (interned, is_var, _) = &info.props[i];
        set_flags[i] = true;
        if *is_var {
            let wrapped = if value.downcast::<RustVar>().is_ok() {
                value
            } else if literal_eligible(&value) {
                let cls_obj =
                    lit_cls.get_or_init(|| RustLiteralVar::type_object_bound(py));
                match RustLiteralVar::create(cls_obj, py, value, None, None) {
                    Ok(v) => v.into_bound(py),
                    // The Python mirror's try/except keeps the raw value on
                    // TypeError — route the whole call there for exactness.
                    Err(_) => return Ok(None),
                }
            } else {
                // Python Var subclass or exotic literal — Python lane.
                return Ok(None);
            };
            mirror.set_item(interned.bind(py), &wrapped)?;
            var_slots[i] = Some(wrapped);
        } else {
            mirror.set_item(interned.bind(py), value)?;
        }
    }
    let mut vars: Vec<Bound<'py, PyAny>> = Vec::new();
    for (i, (_, _, default)) in info.props.iter().enumerate() {
        if let Some(v) = &var_slots[i] {
            vars.push(v.clone());
        } else if !set_flags[i] {
            if let Some(d) = default {
                vars.push(d.bind(py).clone());
            }
        }
    }
    Ok(Some((mirror, PyTuple::new_bound(py, vars))))
}
