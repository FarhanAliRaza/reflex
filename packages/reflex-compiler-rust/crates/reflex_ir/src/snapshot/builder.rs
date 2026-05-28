//! Mutable builder for `Snapshot`. Used by `reflex_pyread::freeze` and the
//! `Stage 6 memoize-arena` pass when they need to push nodes.
//!
//! The builder keeps the `Snapshot` private during construction so callers
//! can only mutate it through these reservation / push entry points. The
//! freeze close pass (`finish_subtree_hashes`) runs once, after the build
//! loop, and fills `propagates_hooks` + `subtree_hash` on every node.

use std::collections::HashSet;
use std::ops::Range;

use xxhash_rust::xxh3::Xxh3;

use reflex_intern::Symbol;

use super::node::{NodeIdx, NodeSnapshot};
use super::Snapshot;

/// Reserves a `NodeIdx` slot then fills it. Used when a parent needs to
/// know its index before its children are built (so it can write the
/// child range later).
pub struct SnapshotBuilder {
    snap: Snapshot,
    /// Build-time set of Python `id()` values for app-wrap component
    /// instances we've already frozen into the arena. Used by Stage 5's
    /// recursive app-wrap freeze to avoid emitting the same wrapper
    /// subtree twice when multiple page nodes contribute the same
    /// wrapper instance.
    app_wrap_seen: HashSet<usize>,
}

impl Default for SnapshotBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl SnapshotBuilder {
    pub fn new() -> Self {
        Self {
            snap: Snapshot::default(),
            app_wrap_seen: HashSet::new(),
        }
    }

    /// Try to register a wrapper component (by Python id) as freshly seen.
    /// Returns `true` on the first call for that id, `false` afterwards —
    /// callers freeze the wrapper subtree only on the first call.
    pub fn mark_app_wrap_seen(&mut self, pyid: usize) -> bool {
        self.app_wrap_seen.insert(pyid)
    }

    /// Reserve a slot for a node that will be filled in later. The returned
    /// index is stable for the rest of the build. Use this when a parent
    /// must be allocated before its children so the parent's
    /// `NodeSnapshot.children` `Range` is contiguous in the arena.
    pub fn reserve(&mut self) -> NodeIdx {
        let idx = self.snap.nodes.len() as NodeIdx;
        self.snap.nodes.push(NodeSnapshot::default());
        self.snap.node_pyids.push(0);
        idx
    }

    /// Append a node and return its index.
    pub fn push(&mut self, node: NodeSnapshot) -> NodeIdx {
        let idx = self.snap.nodes.len() as NodeIdx;
        self.snap.nodes.push(node);
        self.snap.node_pyids.push(0);
        idx
    }

    /// Record the Python `id(component)` for an already-reserved slot.
    pub fn set_pyid(&mut self, idx: NodeIdx, pyid: usize) {
        self.snap.node_pyids[idx as usize] = pyid;
    }

    /// Replace the contents of a previously-reserved slot.
    pub fn fill(&mut self, idx: NodeIdx, node: NodeSnapshot) {
        self.snap.nodes[idx as usize] = node;
    }

    /// Mutable access to a previously-pushed node, e.g. to set its
    /// `children` range after the children have been built.
    pub fn node_mut(&mut self, idx: NodeIdx) -> &mut NodeSnapshot {
        &mut self.snap.nodes[idx as usize]
    }

    /// Mutable access to the underlying snapshot for filling side tables
    /// (control-flow extras, var data, app wraps). Use sparingly — most
    /// code should go through the dedicated reservation methods.
    pub fn snapshot_mut(&mut self) -> &mut Snapshot {
        &mut self.snap
    }

    /// Set the root node index. Defaults to 0; freeze sets this to the
    /// first index it built so codegen can find the page root.
    pub fn set_root(&mut self, root: NodeIdx) {
        self.snap.root = root;
    }

    /// Set a contiguous `children` range on the node at `parent`. Both
    /// `start` and `end` are absolute `nodes` indices.
    pub fn set_children(&mut self, parent: NodeIdx, range: Range<NodeIdx>) {
        self.snap.nodes[parent as usize].children = range;
    }

    /// Run the freeze-close pass: bottom-up fill `subtree_hash` on every
    /// node from its kind + tag + children's hashes. `propagates_hooks`
    /// is set on any node whose hooks_* are non-empty or whose children
    /// propagate (stage 0 has no hooks captured so this stays false
    /// everywhere except where forced by a future stage).
    ///
    /// Bottom-up via a single linear backward pass works because nodes
    /// are pushed in parent-before-children order during freeze, so any
    /// child's index is strictly greater than its parent's — and the
    /// reverse-iteration order visits every child before its parent.
    pub fn finish(mut self) -> Snapshot {
        close_snapshot(&mut self.snap);
        self.snap
    }
}

/// Run the freeze-close pass on an already-populated `Snapshot`: bottom-up
/// fill `subtree_hash` (kind + tag + children's hashes) and bubble up
/// `PROPAGATES_HOOKS`. Shared by `SnapshotBuilder::finish` and by callers
/// that materialize a `Snapshot` without the builder (e.g. the wire-rebuild
/// path, where the Python gatherer cannot compute these Rust-side fields).
///
/// Bottom-up via a single linear backward pass works because nodes are
/// pushed in parent-before-children order, so any child's index is strictly
/// greater than its parent's.
#[inline]
pub fn close_snapshot(snap: &mut Snapshot) {
    let n = snap.nodes.len();
    if n == 0 {
        return;
    }
    for i in (0..n).rev() {
        let (kind, tag, child_range, propagates_from_self) = {
            let node = &snap.nodes[i];
            (
                node.kind,
                node.tag,
                node.children.clone(),
                !node.hooks_internal.is_empty() || !node.hooks_user.is_empty(),
            )
        };
        let mut hasher = Xxh3::new();
        hasher.update(&[kind as u8]);
        hasher.update(&tag.as_u32().to_le_bytes());
        let mut propagates_children = false;
        for child_idx in child_range {
            let child = &snap.nodes[child_idx as usize];
            hasher.update(&child.subtree_hash.to_le_bytes());
            if child
                .flags
                .contains(super::flags::NodeFlags::PROPAGATES_HOOKS)
            {
                propagates_children = true;
            }
        }
        let hash = hasher.digest();
        let node = &mut snap.nodes[i];
        node.subtree_hash = hash;
        node.flags.assign(
            super::flags::NodeFlags::PROPAGATES_HOOKS,
            propagates_from_self || propagates_children,
        );
    }
}

/// Helper for code that knows the parent index up front and wants to
/// build a contiguous children block. Returns the start index for the
/// caller's loop; the caller pushes each child and finally calls
/// `set_children(parent, start..end)` with `end = builder.next_idx()`.
impl SnapshotBuilder {
    /// Index that the next `push`/`reserve` will produce.
    pub fn next_idx(&self) -> NodeIdx {
        self.snap.nodes.len() as NodeIdx
    }

    /// Intern a string into the per-process symbol table. Re-exported
    /// from `reflex_intern` so freeze code doesn't have to import both.
    pub fn intern(s: &str) -> Symbol {
        reflex_intern::intern(s)
    }
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;

    use super::*;
    use crate::snapshot::flags::NodeFlags;
    use crate::snapshot::kinds::NodeKind;

    fn elem(tag: Symbol, children: Range<NodeIdx>) -> NodeSnapshot {
        NodeSnapshot {
            kind: NodeKind::Element,
            tag,
            children,
            ..Default::default()
        }
    }

    #[test]
    fn finish_computes_subtree_hash_bottom_up() {
        // Build:  div
        //          └── span
        //               └── "hi"
        let mut b = SnapshotBuilder::new();
        let root = b.reserve();
        let span = b.reserve();
        let text = b.push(NodeSnapshot {
            kind: NodeKind::Text,
            ..Default::default()
        });
        b.fill(span, elem(intern("span"), text..text + 1));
        b.fill(root, elem(intern("div"), span..span + 1));
        b.set_root(root);
        let snap = b.finish();
        assert_eq!(snap.len(), 3);
        // Hashes must differ across distinct nodes — kind+tag+children differ.
        assert_ne!(snap.node(root).subtree_hash, snap.node(span).subtree_hash);
        assert_ne!(snap.node(span).subtree_hash, snap.node(text).subtree_hash);
        // Hashes must be non-zero (placeholder was 0).
        assert_ne!(snap.node(root).subtree_hash, 0);
    }

    #[test]
    fn finish_subtree_hash_is_deterministic() {
        let build = || {
            let mut b = SnapshotBuilder::new();
            let root = b.reserve();
            let child = b.push(NodeSnapshot {
                kind: NodeKind::Text,
                ..Default::default()
            });
            b.fill(root, elem(intern("p"), child..child + 1));
            b.finish()
        };
        let a = build();
        let b = build();
        assert_eq!(a.node(0).subtree_hash, b.node(0).subtree_hash);
        assert_eq!(a.node(1).subtree_hash, b.node(1).subtree_hash);
    }

    #[test]
    fn finish_propagates_hooks_bottom_up() {
        let mut b = SnapshotBuilder::new();
        let root = b.reserve();
        // Child carries a user hook; flag should bubble up to root.
        let child = b.push(NodeSnapshot {
            kind: NodeKind::Element,
            hooks_user: smallvec::smallvec![super::super::node::HookEntry::new(
                intern("const x = useFoo()"),
                0,
            )],
            ..Default::default()
        });
        b.fill(root, elem(intern("div"), child..child + 1));
        let snap = b.finish();
        assert!(
            snap.node(child).flags.contains(NodeFlags::PROPAGATES_HOOKS),
            "child with user hook should be marked"
        );
        assert!(
            snap.node(root).flags.contains(NodeFlags::PROPAGATES_HOOKS),
            "parent of a propagating child should inherit the flag"
        );
    }

    #[test]
    fn empty_snapshot_finishes_cleanly() {
        let snap = SnapshotBuilder::new().finish();
        assert!(snap.is_empty());
    }
}
