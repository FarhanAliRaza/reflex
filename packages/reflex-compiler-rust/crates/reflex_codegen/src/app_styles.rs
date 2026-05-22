//! Stage 5: arena pass that overlays `App.style[<qualname>]` onto each
//! node's `style` slot. See `rust_port_plan.md` §"Stage 5".
//!
//! The legacy compiler runs `ApplyStylePlugin._apply_style` during a
//! Python tree walk before freeze; that merges the class-level
//! `_add_style()` defaults, the app-level override map keyed by component
//! type, and the instance-level `.style` field into one dict per node.
//! Stage 5 hoists that merge into an arena pass so the freeze pipeline
//! can drop the `_add_style_recursive` step and run
//! `compile_unevaluated_page_no_style` instead — see the
//! `Snapshot.app_style_map` slot the freeze pass exposes.
//!
//! The current implementation is intentionally narrow: it overlays the
//! app-level style only on nodes that don't already carry one. Nodes
//! whose own `.style` is non-empty keep it (matching the legacy
//! plugin's "instance style wins" priority). A future PR can extend
//! this to merge the maps key-by-key once Stage 5's css-emit path is
//! folded into the snapshot.

use reflex_intern::Symbol;
use reflex_ir::Snapshot;

/// Overlay `snapshot.app_style_map` onto matching nodes' `style` slot.
///
/// For every node whose `style_key` (component qualname) is present in
/// the map AND whose current `style` slot is `Symbol::EMPTY`, the slot
/// is set to the mapped CSS expression. Returns the number of nodes
/// affected — handy for tests + observability.
pub fn merge_app_styles_arena_pass(snapshot: &mut Snapshot) -> usize {
    if snapshot.app_style_map.is_empty() {
        return 0;
    }
    let mut overlaid = 0usize;
    for node in &mut snapshot.nodes {
        if node.style != Symbol::EMPTY {
            continue;
        }
        if node.style_key == Symbol::EMPTY {
            continue;
        }
        if let Some(css) = snapshot.app_style_map.get(&node.style_key) {
            node.style = *css;
            overlaid += 1;
        }
    }
    overlaid
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{NodeKind, NodeSnapshot, SnapshotBuilder};

    use super::*;

    #[test]
    fn overlays_only_nodes_without_style() {
        let mut sb = SnapshotBuilder::new();
        let with_style = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            style_key: intern("Box"),
            style: intern("{color: \"blue\"}"),
            ..Default::default()
        });
        let without_style = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("p"),
            style_key: intern("Text"),
            ..Default::default()
        });
        let no_key = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("span"),
            ..Default::default()
        });
        let mut snap = sb.finish();
        snap.app_style_map
            .insert(intern("Box"), intern("{color: \"red\"}"));
        snap.app_style_map
            .insert(intern("Text"), intern("{font: \"bold\"}"));

        let overlaid = merge_app_styles_arena_pass(&mut snap);

        assert_eq!(overlaid, 1);
        // Pre-existing style is preserved.
        assert_eq!(
            snap.node(with_style).style,
            intern("{color: \"blue\"}")
        );
        // Empty style + matching key gets overlaid.
        assert_eq!(
            snap.node(without_style).style,
            intern("{font: \"bold\"}")
        );
        // Node with no style_key is left alone.
        assert_eq!(snap.node(no_key).style, Symbol::EMPTY);
    }

    #[test]
    fn empty_map_is_noop() {
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            style_key: intern("Box"),
            ..Default::default()
        });
        let mut snap = sb.finish();
        assert_eq!(merge_app_styles_arena_pass(&mut snap), 0);
    }
}
