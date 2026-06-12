//! push_node — the mirror's Rust fast lane (plan §4a-bis, §4c-next Stage 1).
//!
//! v1 handles the dominant construction shapes: schema props (native Vars,
//! exact-type literals, Python Vars), str/joined `class_name`, raw base
//! fields, kebab-cased special attrs, and style inputs (dict / list of
//! dicts / Var / Breakpoints plus loose style keys). The classification
//! loop and var harvest run in Rust; the few constructions whose semantics
//! live in Python (`Style(...)`, the synthetic style `Var`, `VarData.merge`)
//! go through cached refs to the very same callables the Python mirror
//! uses — identical by construction. Event kwargs and anything else exotic
//! return `None` and the Python mirror (`_arena_mirror_kwargs`) handles the
//! call unchanged.

use pyo3::prelude::*;
use pyo3::sync::GILProtected;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PySet, PyString, PyTuple, PyType};
use pyo3::PyTypeInfo;
use reflex_vars::{RustLiteralVar, RustVar};
use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::OnceLock;

/// Per-kwarg classification, mirroring `ConstructionSchema.classify` for the
/// names the schema knows. Unknown names fall to special-attr/style handling.
enum Kind {
    /// Index into `MirrorClass::props`.
    Prop(usize),
    Trigger,
    BaseField,
}

struct MirrorClass {
    /// Holds the class so its id stays claimed for the registry's lifetime.
    class_ref: Py<PyAny>,
    /// `(interned name, is_var, Var-valued class default)` in `get_props`
    /// order — the order the `_vars_cache` tuple must follow.
    props: Vec<(Py<PyString>, bool, Option<Py<PyAny>>)>,
    /// kwarg name → classification.
    kinds: HashMap<String, Kind>,
}

/// Python callables/classes the mirror shares with `_arena_mirror_kwargs`,
/// captured once at `reflex_base.components.component` import time.
struct MirrorGlobals {
    /// The Python `Var` ABC (`RustVar` is a registered virtual subclass).
    var_cls: Py<PyAny>,
    breakpoints_cls: Py<PyAny>,
    style_cls: Py<PyAny>,
    /// `VarData.merge` (bound classmethod).
    vardata_merge: Py<PyAny>,
    /// `constants.REFLEX_VAR_OPENING_TAG` — the f-string var marker.
    opening_tag: String,
    s_style: Py<PyString>,
    s_custom_attrs: Py<PyString>,
    s_special_props: Py<PyString>,
    s_class_name: Py<PyString>,
    s_id: Py<PyString>,
    s_key: Py<PyString>,
    s_amp: Py<PyString>,
    s_js_expr: Py<PyString>,
    s_var_type: Py<PyString>,
    s_var_data: Py<PyString>,
}

static GLOBALS: OnceLock<MirrorGlobals> = OnceLock::new();

fn registry() -> &'static GILProtected<RefCell<HashMap<usize, MirrorClass>>> {
    static R: OnceLock<GILProtected<RefCell<HashMap<usize, MirrorClass>>>> = OnceLock::new();
    R.get_or_init(|| GILProtected::new(RefCell::new(HashMap::new())))
}

/// Capture the Python-side classes/callables the fast lane defers to.
/// Called once when `reflex_base.components.component` finishes importing;
/// re-imports are no-ops (first registration wins).
#[pyfunction]
pub fn init_mirror_globals(
    py: Python<'_>,
    var_cls: Bound<'_, PyAny>,
    breakpoints_cls: Bound<'_, PyAny>,
    style_cls: Bound<'_, PyAny>,
    vardata_cls: Bound<'_, PyAny>,
    opening_tag: String,
) -> PyResult<()> {
    let globals = MirrorGlobals {
        vardata_merge: vardata_cls.getattr("merge")?.unbind(),
        var_cls: var_cls.unbind(),
        breakpoints_cls: breakpoints_cls.unbind(),
        style_cls: style_cls.unbind(),
        opening_tag,
        s_style: PyString::intern_bound(py, "style").unbind(),
        s_custom_attrs: PyString::intern_bound(py, "custom_attrs").unbind(),
        s_special_props: PyString::intern_bound(py, "special_props").unbind(),
        s_class_name: PyString::intern_bound(py, "class_name").unbind(),
        s_id: PyString::intern_bound(py, "id").unbind(),
        s_key: PyString::intern_bound(py, "key").unbind(),
        s_amp: PyString::intern_bound(py, "&").unbind(),
        s_js_expr: PyString::intern_bound(py, "_js_expr").unbind(),
        s_var_type: PyString::intern_bound(py, "_var_type").unbind(),
        s_var_data: PyString::intern_bound(py, "_var_data").unbind(),
    };
    let _ = GLOBALS.set(globals);
    Ok(())
}

/// Register a Component class for the fast lane. Called once per class by
/// `Component._arena_create_eligible` with the schema's prop list (in
/// `get_props` order, with the Var-typed flag), the Var-valued class-level
/// prop defaults, and the schema's base-field/trigger name sets.
#[pyfunction]
pub fn register_mirror_class(
    py: Python<'_>,
    cls: Bound<'_, PyAny>,
    props: Vec<(String, bool)>,
    default_vars: Bound<'_, PyDict>,
    base_fields: Vec<String>,
    triggers: Vec<String>,
) -> PyResult<()> {
    let mut kinds = HashMap::with_capacity(props.len() + base_fields.len() + triggers.len());
    let mut plist = Vec::with_capacity(props.len());
    for (i, (name, is_var)) in props.into_iter().enumerate() {
        let default = default_vars.get_item(&name)?.map(Bound::unbind);
        kinds.insert(name.clone(), Kind::Prop(i));
        plist.push((PyString::intern_bound(py, &name).unbind(), is_var, default));
    }
    for name in base_fields {
        kinds.insert(name, Kind::BaseField);
    }
    for name in triggers {
        kinds.insert(name, Kind::Trigger);
    }
    // Reentrant registration (a create() fired from Python code running
    // inside `mirror_props`, e.g. an import triggered by Style conversion)
    // finds the registry borrowed: skip it — the class simply stays on the
    // Python mirror, which is always correct.
    if let Ok(mut reg) = registry().get(py).try_borrow_mut() {
        reg.insert(
            cls.as_ptr() as usize,
            MirrorClass {
                class_ref: cls.unbind(),
                props: plist,
                kinds,
            },
        );
    }
    Ok(())
}

/// Whether `value` is one of the exact types the Python literal dispatch
/// routes to `RustLiteralVar.create` (vars/base.py:1471), restricted to the
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

/// `_is_var` for values already known not to be exact common literals:
/// native Vars settle on the downcast; everything else takes the Python
/// `isinstance(value, Var)` (abc virtual-subclass) check.
fn is_var_value(py: Python<'_>, g: &MirrorGlobals, value: &Bound<'_, PyAny>) -> PyResult<bool> {
    if value.downcast::<RustVar>().is_ok() {
        return Ok(true);
    }
    if literal_eligible(value) {
        return Ok(false);
    }
    value.is_instance(g.var_cls.bind(py))
}

/// Whether `name` is a `data_`/`data-`/`aria_`/`aria-` special attribute
/// (`SpecialAttributes.is_special`).
fn is_special_attr(name: &str) -> bool {
    name.starts_with("data_")
        || name.starts_with("data-")
        || name.starts_with("aria_")
        || name.starts_with("aria-")
}

/// Merge a `Sequence[Mapping]` style input into one fresh dict, like
/// `{k: v for style_dict in style for k, v in style_dict.items()}`.
/// `None` routes the call to the Python lane (a non-dict entry — the
/// Python mirror falls back so `_post_init` raises its TypeError).
fn merge_style_sequence<'py>(
    py: Python<'py>,
    items: &Bound<'py, PyAny>,
) -> PyResult<Option<Bound<'py, PyDict>>> {
    let merged = PyDict::new_bound(py);
    for item in items.iter()? {
        let item = item?;
        let Ok(d) = item.downcast::<PyDict>() else {
            return Ok(None);
        };
        for (k, v) in d.iter() {
            merged.set_item(k, v)?;
        }
    }
    Ok(Some(merged))
}

/// The fast lane: build the mirror dict and `_vars_cache` tuple for a
/// create call. Returns `None` (the Python mirror handles the call
/// unchanged) for event kwargs, unknown `on_*` names, and any value shape
/// whose handling lives outside the ported subset.
#[pyfunction]
pub fn mirror_props<'py>(
    py: Python<'py>,
    cls: &Bound<'py, PyAny>,
    props: &Bound<'py, PyDict>,
) -> PyResult<Option<(Bound<'py, PyDict>, Bound<'py, PyTuple>)>> {
    let Some(g) = GLOBALS.get() else {
        return Ok(None);
    };
    let Ok(reg) = registry().get(py).try_borrow() else {
        // Reentrant create() from Python code running inside an outer
        // mirror_props call — Python lane.
        return Ok(None);
    };
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
    let mut style_kwarg: Option<Bound<'py, PyAny>> = None;
    let mut extra_style: Option<Bound<'py, PyDict>> = None;
    let mut special: Option<Bound<'py, PyDict>> = None;
    for (key, value) in props.iter() {
        let Ok(name) = key.downcast::<PyString>() else {
            return Ok(None);
        };
        let s = name.to_str()?;
        if s == "style" {
            style_kwarg = Some(value);
            continue;
        }
        if s == "event_triggers" {
            // Caller-supplied chain dict — its var harvest needs the Python
            // `_get_vars_from_event_triggers` walk.
            return Ok(None);
        }
        if s == "class_name" {
            // _post_init joins all-str lists/tuples; plain strings and Vars
            // stay raw. Var-bearing lists build a joined Var — Python lane.
            let seq_items: Option<Vec<Bound<'py, PyAny>>> =
                if let Ok(l) = value.downcast_exact::<PyList>() {
                    Some(l.iter().collect())
                } else if let Ok(t) = value.downcast_exact::<PyTuple>() {
                    Some(t.iter().collect())
                } else {
                    None
                };
            if let Some(items) = seq_items {
                let mut parts = Vec::with_capacity(items.len());
                for item in &items {
                    let Ok(part) = item.downcast_exact::<PyString>() else {
                        return Ok(None);
                    };
                    parts.push(part.to_str()?);
                }
                mirror.set_item(key, parts.join(" "))?;
            } else if value.downcast_exact::<PyString>().is_ok()
                || value.downcast::<RustVar>().is_ok()
                || value.is_instance(g.var_cls.bind(py))?
            {
                mirror.set_item(key, value)?;
            } else {
                return Ok(None);
            }
            continue;
        }
        match info.kinds.get(s) {
            Some(Kind::Prop(i)) => {
                let i = *i;
                let (interned, is_var, _) = &info.props[i];
                set_flags[i] = true;
                if *is_var {
                    let wrapped = if value.downcast::<RustVar>().is_ok() {
                        value
                    } else if literal_eligible(&value) {
                        let cls_obj = lit_cls.get_or_init(|| RustLiteralVar::type_object_bound(py));
                        match RustLiteralVar::create(cls_obj, py, value, None, None) {
                            Ok(v) => v.into_bound(py),
                            // The Python mirror's try/except keeps the raw
                            // value on TypeError — route the whole call
                            // there for exactness.
                            Err(_) => return Ok(None),
                        }
                    } else if value.is_instance(g.var_cls.bind(py))? {
                        // Python Var subclass — stored raw, harvested.
                        value
                    } else {
                        // Exotic literal (Decimal, Color, …) — Python lane.
                        return Ok(None);
                    };
                    mirror.set_item(interned.bind(py), &wrapped)?;
                    var_slots[i] = Some(wrapped);
                } else {
                    // Raw store; a Var passed to a non-Var-typed prop is
                    // still harvested (`_arena_build_vars` checks the value,
                    // not the declared type).
                    if is_var_value(py, g, &value)? {
                        var_slots[i] = Some(value.clone());
                    }
                    mirror.set_item(interned.bind(py), value)?;
                }
            }
            Some(Kind::Trigger) => return Ok(None),
            Some(Kind::BaseField) => {
                mirror.set_item(key, value)?;
            }
            None => {
                if s.starts_with("on_") {
                    // Unknown on_* name — fall back so _post_init raises its
                    // ValueError with the valid-triggers message.
                    return Ok(None);
                }
                if is_special_attr(s) {
                    // `to_kebab_case` reduces to `_`→`-` for keys without
                    // uppercase; anything else takes the Python lane.
                    if !s.bytes().all(|b| b.is_ascii() && !b.is_ascii_uppercase()) {
                        return Ok(None);
                    }
                    special
                        .get_or_insert_with(|| PyDict::new_bound(py))
                        .set_item(s.replace('_', "-"), value)?;
                } else {
                    extra_style
                        .get_or_insert_with(|| PyDict::new_bound(py))
                        .set_item(key, value)?;
                }
            }
        }
    }
    if let Some(special) = &special {
        match mirror.get_item(g.s_custom_attrs.bind(py))? {
            // _post_init updates the caller-supplied dict in place.
            Some(custom_attrs) => {
                custom_attrs.call_method1("update", (special,))?;
            }
            None => mirror.set_item(g.s_custom_attrs.bind(py), special)?,
        }
    }
    let mut style_obj: Option<Bound<'py, PyAny>> = None;
    if style_kwarg.is_some() || extra_style.is_some() {
        let base = match &style_kwarg {
            None => PyDict::new_bound(py),
            Some(s) => {
                if s.downcast::<PyString>().is_ok() {
                    // A str is a Sequence of non-Mappings — Python lane
                    // falls back so _post_init raises.
                    return Ok(None);
                }
                if let Ok(d) = s.downcast_exact::<PyDict>() {
                    // Exact dict — the dominant shape; can't be Breakpoints
                    // (a dict subclass) or a Var, so skip those checks.
                    d.copy()?
                } else if s.downcast::<PyList>().is_ok() || s.downcast::<PyTuple>().is_ok() {
                    match merge_style_sequence(py, s)? {
                        Some(merged) => merged,
                        None => return Ok(None),
                    }
                } else if s.is_instance(g.breakpoints_cls.bind(py))?
                    || s.downcast::<RustVar>().is_ok()
                    || s.is_instance(g.var_cls.bind(py))?
                {
                    // Breakpoints checked before the dict branch — it is a
                    // dict subclass that must wrap under "&" instead.
                    let wrapped = PyDict::new_bound(py);
                    wrapped.set_item(g.s_amp.bind(py), s)?;
                    wrapped
                } else if let Ok(d) = s.downcast::<PyDict>() {
                    d.copy()?
                } else {
                    // Non-dict Mapping or other exotic shape — Python lane.
                    return Ok(None);
                }
            }
        };
        if let Some(extra) = &extra_style {
            for (k, v) in extra.iter() {
                base.set_item(k, v)?;
            }
        }
        // The same `Style({**style, **shorthands})` call the Python mirror
        // makes; conversion errors propagate identically.
        let style_inst = g.style_cls.bind(py).call1((base,))?;
        mirror.set_item(g.s_style.bind(py), &style_inst)?;
        style_obj = Some(style_inst);
    }
    // The var harvest, in `_arena_build_vars` order: prop vars (class
    // defaults for unset props), the synthetic style var, special props,
    // then the identity props with the f-string VarData collapse. No event
    // vars — event kwargs returned `None` above.
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
    if let Some(style_inst) = &style_obj {
        let style_dict = style_inst.downcast::<PyDict>()?;
        if !style_dict.is_empty() {
            let vd = style_inst.getattr(g.s_var_data.bind(py))?;
            let merged = g.vardata_merge.bind(py).call1((vd,))?;
            let kwargs = PyDict::new_bound(py);
            kwargs.set_item(g.s_js_expr.bind(py), g.s_style.bind(py))?;
            kwargs.set_item(g.s_var_type.bind(py), PyString::type_object_bound(py))?;
            kwargs.set_item(g.s_var_data.bind(py), merged)?;
            vars.push(g.var_cls.bind(py).call((), Some(&kwargs))?);
        }
    }
    if let Some(special_props) = mirror.get_item(g.s_special_props.bind(py))? {
        let Ok(items) = special_props.downcast::<PyList>() else {
            return Ok(None);
        };
        for item in items.iter() {
            vars.push(item);
        }
    }
    let custom_attrs = mirror.get_item(g.s_custom_attrs.bind(py))?;
    let custom_attr_values: Vec<Bound<'py, PyAny>> = match &custom_attrs {
        Some(ca) => {
            let Ok(d) = ca.downcast_exact::<PyDict>() else {
                // dict subclass — `.values()` could be overridden.
                return Ok(None);
            };
            d.iter().map(|(_, v)| v).collect()
        }
        None => Vec::new(),
    };
    for comp_prop in [
        mirror.get_item(g.s_class_name.bind(py))?,
        mirror.get_item(g.s_id.bind(py))?,
        mirror.get_item(g.s_key.bind(py))?,
    ]
    .into_iter()
    .flatten()
    .chain(custom_attr_values)
    {
        if comp_prop.downcast::<RustVar>().is_ok() {
            vars.push(comp_prop);
        } else if let Ok(s) = comp_prop.downcast_exact::<PyString>() {
            if s.to_str()?.contains(&g.opening_tag) {
                let cls_obj = lit_cls.get_or_init(|| RustLiteralVar::type_object_bound(py));
                // Exact str routes to this same entry in the Python
                // dispatch (vars/base.py:1471).
                let Ok(var) = RustLiteralVar::create(cls_obj, py, comp_prop, None, None) else {
                    return Ok(None);
                };
                let var = var.into_bound(py);
                if !var.call_method0("_get_all_var_data")?.is_none() {
                    vars.push(var);
                }
            }
        } else if comp_prop.downcast::<PyString>().is_ok() {
            // str subclass — its literal dispatch differs; Python lane.
            return Ok(None);
        } else if comp_prop.is_instance(g.var_cls.bind(py))? {
            vars.push(comp_prop);
        }
    }
    Ok(Some((mirror, PyTuple::new_bound(py, vars))))
}
