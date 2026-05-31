//! Guards the per-node memory budget for the flat snapshot IR.
//!
//! `NodeSnapshot` is the hot type — every Reflex page evaluation
//! materializes one per Component. Stage 0 measured ~232 bytes on
//! x86_64; the 256-byte ceiling buys headroom while keeping the per-page
//! arena fit in L1/L2 for medium pages (~165 nodes ≈ 42 KiB).
//!
//! `NodeFlags` is a `u16` newtype; verify the layout didn't accidentally
//! grow to a wider type.

use std::mem::size_of;

use reflex_ir::{NodeFlags, NodeSnapshot};

#[test]
fn node_snapshot_within_budget() {
    let actual = size_of::<NodeSnapshot>();
    assert!(
        actual <= 256,
        "NodeSnapshot grew to {actual} bytes; the 256-byte budget keeps a 165-node page under 42 KiB"
    );
}

#[test]
fn node_flags_is_two_bytes() {
    assert_eq!(size_of::<NodeFlags>(), 2);
}
