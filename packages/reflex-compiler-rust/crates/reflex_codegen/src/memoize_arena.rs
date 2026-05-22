//! Stage 3 memoize-decision walk. Reads the `NodeFlags` bits that the
//! freeze pass populated on every snapshot node.
//!
//! Today the legacy `_should_memoize` predicate (in
//! `reflex_base.components.memoize_helpers`) does a recursive subtree
//! walk to find state references / event handlers. The freeze pass
//! captures the same information per-node into `HAS_STATE_OR_HOOKS` and
//! `HAS_EVENT_TRIGGERS`; this function rolls them up via the cached
//! `PROPAGATES_HOOKS` bit so the decision is a single bit test plus a
//! disposition lookup.
//!
//! Disposition bits 5-6 of `NodeFlags`:
//!
//! - `Auto` (00) — memoize iff the subtree carries state or events.
//! - `Never` (01) — short-circuit to `false`.
//! - `Always` (10) — short-circuit to `true`.

use reflex_ir::{MemoizationDisposition, NodeFlags, NodeIdx, Snapshot};

/// Return `true` iff the subtree rooted at `node_idx` should be memoized.
///
/// Stage 3 makes this a single bit-test by relying on
/// `NodeFlags::PROPAGATES_HOOKS` to summarize the subtree's state/event
/// content. The freeze close pass in `SnapshotBuilder::finish` rolls
/// `HAS_STATE_OR_HOOKS` up the tree into `PROPAGATES_HOOKS`, so any
/// descendant with state/events surfaces here.
pub fn should_memoize_arena(snapshot: &Snapshot, node_idx: NodeIdx) -> bool {
    let node = snapshot.node(node_idx);
    let flags = node.flags;
    match flags.memoization_disposition() {
        MemoizationDisposition::Never => false,
        MemoizationDisposition::Always => true,
        MemoizationDisposition::Auto => {
            flags.contains(NodeFlags::PROPAGATES_HOOKS)
                || flags.contains(NodeFlags::HAS_STATE_OR_HOOKS)
                || flags.contains(NodeFlags::HAS_EVENT_TRIGGERS)
        }
    }
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{HookEntry, NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::smallvec;

    use super::*;

    #[allow(unused_imports)]
    use HookEntry as _Use;

    #[test]
    fn auto_with_no_hooks_returns_false() {
        let mut b = SnapshotBuilder::new();
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        });
        let snap = b.finish();
        assert!(!should_memoize_arena(&snap, 0));
    }

    #[test]
    fn auto_with_state_hook_returns_true() {
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            hooks_internal: smallvec![HookEntry::new(intern("const x = useState(0)"), 0)],
            ..Default::default()
        };
        node.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        b.push(node);
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, 0));
    }

    #[test]
    fn never_disposition_short_circuits() {
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        };
        node.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        node.flags
            .set_memoization_disposition(MemoizationDisposition::Never);
        b.push(node);
        let snap = b.finish();
        assert!(!should_memoize_arena(&snap, 0));
    }

    #[test]
    fn always_disposition_overrides_no_state() {
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        };
        node.flags
            .set_memoization_disposition(MemoizationDisposition::Always);
        b.push(node);
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, 0));
    }

    #[test]
    fn auto_propagates_from_child() {
        // Parent has no hooks; child does. The finish pass should bubble
        // PROPAGATES_HOOKS to the parent.
        let mut b = SnapshotBuilder::new();
        let parent = b.reserve();
        let mut child = NodeSnapshot {
            kind: NodeKind::Element,
            hooks_internal: smallvec![HookEntry::new(intern("const x = useState(0)"), 0)],
            ..Default::default()
        };
        child.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        let child_idx = b.push(child);
        b.fill(
            parent,
            NodeSnapshot {
                kind: NodeKind::Element,
                children: child_idx..child_idx + 1,
                ..Default::default()
            },
        );
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, parent));
        assert!(should_memoize_arena(&snap, child_idx));
    }
}
