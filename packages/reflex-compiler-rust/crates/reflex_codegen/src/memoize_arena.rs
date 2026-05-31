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

use reflex_ir::{MemoizationDisposition, NodeFlags, NodeIdx, NodeKind, Snapshot};

/// Return `true` iff the subtree rooted at `node_idx` should be memoized.
///
/// PR3: full parity rewrite of
/// `reflex.compiler.plugins.memoize._should_memoize` as 8 bit-tests +
/// one enum match per node. Reads the freeze-populated flags only —
/// no `getattr`, no Var walks.
///
/// Decision logic (mirrors `_should_memoize` order):
///
/// 1. `disposition == Never`        → `false`
/// 2. `IS_BARE`                     → `HAS_STATE_OR_HOOKS`
/// 3. `tag is None` AND not Cond/Match AND not structural memo child
///                                  → `false` (early skip)
/// 4. `disposition == Always`       → `true`
/// 5. direct prop-Var reactivity    → `HAS_STATE_OR_HOOKS` OR
///                                    `HAS_EVENT_TRIGGERS`
/// 6. structural memo child (Foreach) that is NOT a snapshot boundary
///                                  → `true` (MemoizationStrategy::SNAPSHOT
///                                    when `is_snapshot_boundary` is false)
/// 7. `IS_SNAPSHOT_BOUNDARY` AND reactive descendants
///                                  → `true` (PROPAGATES_HOOKS already
///                                    bubbled up via `SnapshotBuilder::finish`)
///
/// Per-node cost: ~15-20 ns.
#[inline]
pub fn should_memoize_arena(snapshot: &Snapshot, node_idx: NodeIdx) -> bool {
    let n = snapshot.node(node_idx);
    let f = n.flags;

    // Disposition NEVER short-circuits before anything else.
    if matches!(f.memoization_disposition(), MemoizationDisposition::Never) {
        return false;
    }

    // Bare: stateful contents Var → memoize. The freeze pass (PR2) sets
    // HAS_STATE_OR_HOOKS for Bare nodes whose contents Var carries
    // reactive var_data.
    if f.contains(NodeFlags::IS_BARE) {
        return f.contains(NodeFlags::HAS_STATE_OR_HOOKS);
    }

    // Tag-less, non-control-flow, non-structural-memo-child → skip.
    // Cond/Match render conditional branch JSX even with `tag=None`;
    // Foreach is the only structural memo child case.
    if f.contains(NodeFlags::TAG_IS_NONE)
        && !matches!(n.kind, NodeKind::Cond | NodeKind::Match)
        && !f.contains(NodeFlags::IS_STRUCTURAL_MEMO_CHILD)
    {
        return false;
    }

    // ALWAYS short-circuits after the tag-none early skip — matches the
    // Python ordering exactly so an `ALWAYS` Bare with no contents-Var
    // reactivity still goes through the Bare branch above (which
    // returns false for non-reactive Bares).
    if matches!(f.memoization_disposition(), MemoizationDisposition::Always) {
        return true;
    }

    // Direct prop-Var reactivity (HAS_STATE_OR_HOOKS set by PR2 freeze
    // when any rendered_props Var has non-empty state/hooks/components).
    // HAS_EVENT_TRIGGERS captures `bool(component.event_triggers)`.
    if f.contains(NodeFlags::HAS_STATE_OR_HOOKS) || f.contains(NodeFlags::HAS_EVENT_TRIGGERS) {
        return true;
    }

    // Structural-memo-child (Foreach) that is NOT a snapshot boundary →
    // `MemoizationStrategy::SNAPSHOT` and Python wraps unconditionally.
    if f.contains(NodeFlags::IS_STRUCTURAL_MEMO_CHILD)
        && !f.contains(NodeFlags::IS_SNAPSHOT_BOUNDARY)
    {
        return true;
    }

    // Snapshot boundary with reactive descendants → wrap whole subtree.
    // `PROPAGATES_HOOKS` is bubbled up from descendants by the finish
    // close pass.
    if f.contains(NodeFlags::IS_SNAPSHOT_BOUNDARY) && f.contains(NodeFlags::PROPAGATES_HOOKS) {
        return true;
    }

    false
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
    fn auto_propagates_from_child_only_when_snapshot_boundary() {
        // PR3: a parent without its own state/events isn't memoized
        // just because a descendant has state — Python's
        // `_should_memoize` evaluates each node from its OWN
        // props/triggers. Descendants are walked independently. The
        // exception is `IS_SNAPSHOT_BOUNDARY` parents, which DO wrap
        // when descendants are reactive (PROPAGATES_HOOKS rolls up).
        let mut b = SnapshotBuilder::new();
        let parent = b.reserve();
        let mut child = NodeSnapshot {
            kind: NodeKind::Element,
            hooks_internal: smallvec![HookEntry::new(intern("const x = useState(0)"), 0)],
            ..Default::default()
        };
        child.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        let child_idx = b.push(child);
        let mut parent_node = NodeSnapshot {
            kind: NodeKind::Element,
            children: child_idx..child_idx + 1,
            tag: intern("div"),
            ..Default::default()
        };
        parent_node.flags.set(NodeFlags::IS_SNAPSHOT_BOUNDARY);
        b.fill(parent, parent_node);
        let snap = b.finish();
        // Snapshot-boundary parent wraps because reactive child bubbled
        // PROPAGATES_HOOKS up.
        assert!(should_memoize_arena(&snap, parent));
        // Reactive child wraps on its own state.
        assert!(should_memoize_arena(&snap, child_idx));
    }

    #[test]
    fn auto_does_not_wrap_parent_when_only_child_reactive() {
        // Without IS_SNAPSHOT_BOUNDARY a parent stays unwrapped — the
        // descendant handles its own memoization.
        let mut b = SnapshotBuilder::new();
        let parent = b.reserve();
        let mut child = NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("span"),
            ..Default::default()
        };
        child.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        let child_idx = b.push(child);
        b.fill(
            parent,
            NodeSnapshot {
                kind: NodeKind::Element,
                tag: intern("div"),
                children: child_idx..child_idx + 1,
                ..Default::default()
            },
        );
        let snap = b.finish();
        assert!(!should_memoize_arena(&snap, parent));
        assert!(should_memoize_arena(&snap, child_idx));
    }

    #[test]
    fn tag_none_non_control_flow_is_skipped() {
        // A node with `tag=None`, kind=Element, not Foreach → never
        // memoized regardless of HAS_STATE_OR_HOOKS or HAS_EVENT_TRIGGERS.
        // Matches the early-skip in `_should_memoize` lines 162-167.
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        };
        node.flags.set(NodeFlags::TAG_IS_NONE);
        node.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        b.push(node);
        let snap = b.finish();
        assert!(!should_memoize_arena(&snap, 0));
    }

    #[test]
    fn structural_memo_child_wraps_when_not_boundary() {
        // Foreach (IS_STRUCTURAL_MEMO_CHILD) that is NOT a snapshot
        // boundary → unconditionally wraps (SNAPSHOT strategy).
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Foreach,
            ..Default::default()
        };
        node.flags.set(NodeFlags::TAG_IS_NONE);
        node.flags.set(NodeFlags::IS_STRUCTURAL_MEMO_CHILD);
        b.push(node);
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, 0));
    }

    #[test]
    fn snapshot_boundary_wraps_when_subtree_reactive() {
        // IS_SNAPSHOT_BOUNDARY parent + reactive descendant → wraps the
        // whole subtree. Mirrors `_should_memoize` line 187. The
        // PROPAGATES_HOOKS bit bubbles up from descendants whose
        // `hooks_internal`/`hooks_user` are non-empty (see
        // `SnapshotBuilder::finish`).
        let mut b = SnapshotBuilder::new();
        let parent = b.reserve();
        let mut child = NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("button"),
            hooks_internal: smallvec![HookEntry::new(intern("const x = useState(0)"), 0)],
            ..Default::default()
        };
        child.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        let child_idx = b.push(child);
        let mut parent_node = NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("Upload"),
            children: child_idx..child_idx + 1,
            ..Default::default()
        };
        parent_node.flags.set(NodeFlags::IS_SNAPSHOT_BOUNDARY);
        b.fill(parent, parent_node);
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, parent));
    }

    #[test]
    fn event_triggers_wrap_even_without_state() {
        // `bool(component.event_triggers)` → memoize. Mirrors line 191.
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("button"),
            ..Default::default()
        };
        node.flags.set(NodeFlags::HAS_EVENT_TRIGGERS);
        b.push(node);
        let snap = b.finish();
        assert!(should_memoize_arena(&snap, 0));
    }

    #[test]
    fn bare_without_reactive_contents_is_not_wrapped() {
        // PR3: a Bare wrapping a non-reactive Var (e.g. a string
        // literal) must not memoize. The freeze pass leaves
        // HAS_STATE_OR_HOOKS unset in that case.
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        };
        node.flags.set(NodeFlags::IS_BARE);
        node.flags.set(NodeFlags::TAG_IS_NONE);
        b.push(node);
        let snap = b.finish();
        assert!(!should_memoize_arena(&snap, 0));
    }
}
