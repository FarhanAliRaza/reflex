//! Page-level harvest walks over a `reflex_ir::Snapshot`.
//!
//! Stage 1 of the Rust port (`rust_port_plan.md`). Replaces the
//! aggregate walks in `Component._get_all_*`:
//!
//! - [`collect_imports`] — module-scope `import { … } from "<module>"`
//!   pairs, deduped in observation order. Mirrors
//!   `Component._get_all_imports` reduced to JSX-block shape.
//! - [`collect_custom_code`] — distinct custom-code blocks in DFS order.
//! - [`collect_dynamic_imports`] — distinct dynamic-import statements.
//! - [`collect_refs`] — interned ref identifiers in observation order.
//!
//! All walks are linear scans over `Snapshot.nodes`; the snapshot's
//! parent-before-children invariant means observation order matches DFS.

use std::collections::HashSet;

use reflex_intern::Symbol;
use reflex_ir::{ImportEntry, NodeIdx, Snapshot};

/// Deduplicated `(module, name)` pairs across every node in `snapshot`.
/// Observation order matches the freeze walk (parent-before-children DFS),
/// so two freezes of the same tree produce the same result list.
pub fn collect_imports(snapshot: &Snapshot) -> Vec<ImportEntry> {
    let mut seen: HashSet<(Symbol, Symbol)> = HashSet::new();
    let mut out: Vec<ImportEntry> = Vec::new();
    for node in &snapshot.nodes {
        for entry in &node.imports {
            if seen.insert((entry.module, entry.name)) {
                out.push(*entry);
            }
        }
    }
    out
}

/// Distinct custom-code blocks, observation order. Skips
/// `Symbol::EMPTY` slots. Per node: the node's own `_get_custom_code`
/// block first, then its `add_custom_code` MRO contributions — the same
/// order as legacy `_get_all_custom_code`.
pub fn collect_custom_code(snapshot: &Snapshot) -> Vec<Symbol> {
    let mut seen: HashSet<Symbol> = HashSet::new();
    let mut out: Vec<Symbol> = Vec::new();
    let mut push = |code: Symbol, seen: &mut HashSet<Symbol>, out: &mut Vec<Symbol>| {
        if code != Symbol::EMPTY && seen.insert(code) {
            out.push(code);
        }
    };
    for (idx, node) in snapshot.nodes.iter().enumerate() {
        push(node.custom_code, &mut seen, &mut out);
        if let Some(extra) = snapshot
            .control_flow
            .custom_code_extra
            .get(&(idx as NodeIdx))
        {
            for code in extra {
                push(*code, &mut seen, &mut out);
            }
        }
    }
    out
}

/// Distinct dynamic-import statements, observation order.
pub fn collect_dynamic_imports(snapshot: &Snapshot) -> Vec<Symbol> {
    let mut seen: HashSet<Symbol> = HashSet::new();
    let mut out: Vec<Symbol> = Vec::new();
    for node in &snapshot.nodes {
        for sym in &node.dynamic_imports {
            if *sym == Symbol::EMPTY {
                continue;
            }
            if seen.insert(*sym) {
                out.push(*sym);
            }
        }
    }
    out
}

/// Interned ref identifiers in observation order, skipping nodes with
/// no ref. The legacy Python `_get_all_refs` returns a `dict[str, None]`;
/// callers that need the dict shape wrap the result.
pub fn collect_refs(snapshot: &Snapshot) -> Vec<Symbol> {
    let mut seen: HashSet<Symbol> = HashSet::new();
    let mut out: Vec<Symbol> = Vec::new();
    for node in &snapshot.nodes {
        let r = node.ref_name;
        if r == Symbol::EMPTY {
            continue;
        }
        if seen.insert(r) {
            out.push(r);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{ImportEntry, NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::smallvec;

    use super::*;

    fn make_snapshot(per_node_imports: &[&[(Symbol, Symbol)]]) -> Snapshot {
        let mut b = SnapshotBuilder::new();
        for entries in per_node_imports {
            let mut node = NodeSnapshot::default();
            node.kind = NodeKind::Element;
            for (m, n) in *entries {
                node.imports.push(ImportEntry::new(*m, *n));
            }
            b.push(node);
        }
        b.finish()
    }

    #[test]
    fn collect_imports_dedupes_and_keeps_first_order() {
        let react = intern("react");
        let use_state = intern("useState");
        let use_effect = intern("useEffect");
        let snap = make_snapshot(&[
            &[(react, use_state)],
            &[(react, use_state), (react, use_effect)],
        ]);
        let out = collect_imports(&snap);
        assert_eq!(
            out,
            vec![
                ImportEntry::new(react, use_state),
                ImportEntry::new(react, use_effect),
            ]
        );
    }

    #[test]
    fn collect_refs_skips_empty_and_dedupes() {
        let mut b = SnapshotBuilder::new();
        let id_a = intern("ref_a");
        let id_b = intern("ref_b");
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            ref_name: id_a,
            ..Default::default()
        });
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            ..Default::default()
        });
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            ref_name: id_a, // dupe
            ..Default::default()
        });
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            ref_name: id_b,
            ..Default::default()
        });
        let snap = b.finish();
        assert_eq!(collect_refs(&snap), vec![id_a, id_b]);
    }

    #[test]
    fn collect_dynamic_imports_handles_smallvec_overflow() {
        let mut b = SnapshotBuilder::new();
        let a = intern("import('a')");
        let bsym = intern("import('b')");
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            dynamic_imports: smallvec![a, bsym],
            ..Default::default()
        });
        b.push(NodeSnapshot {
            kind: NodeKind::Element,
            dynamic_imports: smallvec![a], // dup
            ..Default::default()
        });
        let snap = b.finish();
        assert_eq!(collect_dynamic_imports(&snap), vec![a, bsym]);
    }

    #[test]
    fn empty_snapshot_collects_empty_vectors() {
        let snap = SnapshotBuilder::new().finish();
        assert!(collect_imports(&snap).is_empty());
        assert!(collect_custom_code(&snap).is_empty());
        assert!(collect_dynamic_imports(&snap).is_empty());
        assert!(collect_refs(&snap).is_empty());
    }
}
