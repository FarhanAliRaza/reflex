//! Spike: handle-based construction feasibility (Stage 2 proof).
//!
//! NOT production. Proves two numbers that decide whether component
//! construction can move into Rust behind a thin Python handle:
//!   1. cost of building a node via one PyO3 call + slotted handle vs
//!      today's `Component.create` (~13 µs/leaf), and
//!   2. cost of an attribute read proxied from the handle into the arena
//!      (the operation override-parents like DebounceInput/forms do on
//!      their children — the load-bearing unknown for mixed trees).
//!
//! Model is a lower bound: props are kept as the original `PyDict` rather
//! than parsed to IR, so real construction can only be at or above this
//! build cost and at or below this read cost.

use pyo3::prelude::*;
use pyo3::sync::GILProtected;
use pyo3::types::{PyDict, PyString};
use std::cell::RefCell;
use std::sync::OnceLock;

struct SpikeNode {
    tag: Py<PyString>,
    props: Py<PyDict>,
    children: Vec<usize>,
}

fn arena() -> &'static GILProtected<RefCell<Vec<SpikeNode>>> {
    static A: OnceLock<GILProtected<RefCell<Vec<SpikeNode>>>> = OnceLock::new();
    A.get_or_init(|| GILProtected::new(RefCell::new(Vec::new())))
}

/// Build a node natively: store tag/props/children in the arena, return
/// the index. One PyO3 crossing; no Python Component object.
#[pyfunction]
pub fn spike_push_node(
    py: Python<'_>,
    tag: Py<PyString>,
    props: Py<PyDict>,
    children: Vec<usize>,
) -> usize {
    let mut a = arena().get(py).borrow_mut();
    a.push(SpikeNode {
        tag,
        props,
        children,
    });
    a.len() - 1
}

/// Proxy an attribute read from a handle into the arena node: the prop
/// value if present, else the tag for `"tag"`, else `None`. This is what a
/// thin handle's `__getattr__` would do.
#[pyfunction]
pub fn spike_node_attr(py: Python<'_>, idx: usize, name: &str) -> Option<Py<PyAny>> {
    let a = arena().get(py).borrow();
    let node = a.get(idx)?;
    if name == "tag" {
        return Some(node.tag.clone_ref(py).into_any());
    }
    node.props
        .bind(py)
        .get_item(name)
        .ok()
        .flatten()
        .map(|v| v.unbind())
}

/// Number of children of a node (proxy for the freeze walking the arena).
#[pyfunction]
pub fn spike_node_child_count(py: Python<'_>, idx: usize) -> usize {
    arena()
        .get(py)
        .borrow()
        .get(idx)
        .map(|n| n.children.len())
        .unwrap_or(0)
}

/// Clear the arena between benchmark runs.
#[pyfunction]
pub fn spike_reset(py: Python<'_>) {
    arena().get(py).borrow_mut().clear();
}
