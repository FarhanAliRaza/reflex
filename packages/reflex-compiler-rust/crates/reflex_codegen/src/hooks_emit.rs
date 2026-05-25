//! Stage 2 hooks emitter. Mirrors
//! `reflex_base.compiler.templates._render_hooks`.
//!
//! Takes a snapshot, aggregates per-node `hooks_internal` + `hooks_user`,
//! sorts by `HookEntry.position` bucket (0 = INTERNAL, 1 = PRE_TRIGGER,
//! 2 = POST_TRIGGER), joins inside each bucket with newlines, then
//! concatenates `internal \n pre_trigger \n memo \n post_trigger`. The
//! result is the rendered hooks body the page template splices between
//! the state-context hooks and `return`.

use std::collections::HashSet;

use reflex_intern::{resolve_unchecked, Symbol};
use reflex_ir::{HookEntry, NodeIdx, Snapshot};

/// Returns `(internal, pre_trigger, post_trigger, memo)` joined into one
/// `\n`-separated string in the legacy order. `memo` lines are spliced
/// between pre and post trigger buckets; pass an empty slice if none.
///
/// Per-bucket dedupe runs on the hook code symbol so the same hook
/// declared on multiple Components doesn't get repeated.
pub fn render_hooks(snapshot: &Snapshot, memo_lines: &[&str]) -> String {
    let (internal, pre_trigger, post_trigger) = bucket_hooks(snapshot);
    let mut out = String::with_capacity(estimate_size(&internal, &pre_trigger, &post_trigger));
    write_bucket(&mut out, &internal);
    out.push('\n');
    write_bucket(&mut out, &pre_trigger);
    out.push('\n');
    if !memo_lines.is_empty() {
        for (i, line) in memo_lines.iter().enumerate() {
            if i > 0 {
                out.push('\n');
            }
            out.push_str(line);
        }
    }
    out.push('\n');
    write_bucket(&mut out, &post_trigger);
    out
}

fn bucket_hooks(snapshot: &Snapshot) -> (Vec<Symbol>, Vec<Symbol>, Vec<Symbol>) {
    let mut seen: HashSet<Symbol> = HashSet::new();
    let mut internal: Vec<Symbol> = Vec::new();
    let mut pre: Vec<Symbol> = Vec::new();
    let mut post: Vec<Symbol> = Vec::new();
    for node in &snapshot.nodes {
        for h in node.hooks_internal.iter().chain(node.hooks_user.iter()) {
            push_bucket(&mut seen, &mut internal, &mut pre, &mut post, *h);
        }
    }
    (internal, pre, post)
}

/// PR4: hooks emit restricted to the subtree rooted at `root`. Used
/// by `emit_memo_module_from_snapshot` so a memo body only sees the
/// `useState`/`useCallback`/etc. declarations for the nodes it owns —
/// not the entire page's hook set.
///
/// Mirrors `render_hooks` (page-global) but walks only the subtree DFS
/// following `node.children` ranges. The traversal does NOT follow
/// `wrap_redirects` — a body's subtree is the original captured
/// content, not the synthetic wrapper.
pub fn render_hooks_for_subtree(snapshot: &Snapshot, root: NodeIdx, memo_lines: &[&str]) -> String {
    let (internal, pre_trigger, post_trigger) = bucket_subtree_hooks(snapshot, root);
    let mut out = String::with_capacity(estimate_size(&internal, &pre_trigger, &post_trigger));
    write_bucket(&mut out, &internal);
    out.push('\n');
    write_bucket(&mut out, &pre_trigger);
    out.push('\n');
    if !memo_lines.is_empty() {
        for (i, line) in memo_lines.iter().enumerate() {
            if i > 0 {
                out.push('\n');
            }
            out.push_str(line);
        }
    }
    out.push('\n');
    write_bucket(&mut out, &post_trigger);
    out
}

fn bucket_subtree_hooks(
    snapshot: &Snapshot,
    root: NodeIdx,
) -> (Vec<Symbol>, Vec<Symbol>, Vec<Symbol>) {
    let mut seen: HashSet<Symbol> = HashSet::new();
    let mut internal: Vec<Symbol> = Vec::new();
    let mut pre: Vec<Symbol> = Vec::new();
    let mut post: Vec<Symbol> = Vec::new();
    let mut stack: Vec<NodeIdx> = vec![root];
    while let Some(idx) = stack.pop() {
        // Defensive bounds check — bad freeze input shouldn't panic.
        if (idx as usize) >= snapshot.nodes.len() {
            continue;
        }
        let node = snapshot.node(idx);
        for h in node.hooks_internal.iter().chain(node.hooks_user.iter()) {
            push_bucket(&mut seen, &mut internal, &mut pre, &mut post, *h);
        }
        for child in node.children.clone() {
            stack.push(child);
        }
    }
    (internal, pre, post)
}

fn push_bucket(
    seen: &mut HashSet<Symbol>,
    internal: &mut Vec<Symbol>,
    pre: &mut Vec<Symbol>,
    post: &mut Vec<Symbol>,
    h: HookEntry,
) {
    if h.code == Symbol::EMPTY {
        return;
    }
    if !seen.insert(h.code) {
        return;
    }
    // PR4: skip the page-shell hooks Rust emits unconditionally
    // (`useContext(StateContexts.…)`, `useContext(EventLoopContext)`).
    // The freeze pass captures these in `hooks_user`/`hooks_internal`
    // for parity with the Python `_get_hooks` aggregation; the page +
    // memo module emitters then would double-declare them. Mirrors the
    // filter in `rust_pipeline.py::compile_pages` that strips the same
    // lines before sending `hooks_body` to the legacy emit path.
    let code = reflex_intern::resolve_unchecked(h.code);
    if code.contains("useContext(StateContexts.") || code.contains("useContext(EventLoopContext)") {
        return;
    }
    match h.position {
        0 => internal.push(h.code),
        // POST_TRIGGER is the only "after triggers" bucket; everything
        // else (including unset) falls into PRE_TRIGGER, mirroring the
        // Python `_sort_hooks` else-branch.
        2 => post.push(h.code),
        _ => pre.push(h.code),
    }
}

fn write_bucket(out: &mut String, bucket: &[Symbol]) {
    for (i, sym) in bucket.iter().enumerate() {
        if i > 0 {
            out.push('\n');
        }
        out.push_str(resolve_unchecked(*sym));
    }
}

fn estimate_size(internal: &[Symbol], pre: &[Symbol], post: &[Symbol]) -> usize {
    let mut total = 16;
    for bucket in [internal, pre, post] {
        for sym in bucket {
            total += resolve_unchecked(*sym).len() + 1;
        }
    }
    total
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{HookEntry, NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::smallvec;

    use super::*;

    fn make_snapshot(hooks: &[(u8, &str)]) -> Snapshot {
        let mut b = SnapshotBuilder::new();
        let mut node = NodeSnapshot::default();
        node.kind = NodeKind::Element;
        for (pos, code) in hooks {
            node.hooks_internal
                .push(HookEntry::new(intern(code), *pos));
        }
        b.push(node);
        b.finish()
    }

    #[test]
    fn order_is_internal_pre_post() {
        let snap = make_snapshot(&[
            (2, "// post line"),
            (0, "const x = useState(0)"),
            (1, "// pre line"),
        ]);
        let out = render_hooks(&snap, &[]);
        let pos_internal = out.find("const x = useState(0)").unwrap();
        let pos_pre = out.find("// pre line").unwrap();
        let pos_post = out.find("// post line").unwrap();
        assert!(pos_internal < pos_pre);
        assert!(pos_pre < pos_post);
    }

    #[test]
    fn dedupes_across_nodes() {
        let mut b = SnapshotBuilder::new();
        let hook = intern("const a = useFoo()");
        let mk = || NodeSnapshot {
            kind: NodeKind::Element,
            hooks_internal: smallvec![HookEntry::new(hook, 0)],
            ..Default::default()
        };
        b.push(mk());
        b.push(mk());
        let snap = b.finish();
        let out = render_hooks(&snap, &[]);
        assert_eq!(out.matches("const a = useFoo()").count(), 1);
    }

    #[test]
    fn memo_lines_splice_between_pre_and_post() {
        let snap = make_snapshot(&[(1, "// pre"), (2, "// post")]);
        let out = render_hooks(&snap, &["// memo line"]);
        let pos_pre = out.find("// pre").unwrap();
        let pos_memo = out.find("// memo line").unwrap();
        let pos_post = out.find("// post").unwrap();
        assert!(pos_pre < pos_memo);
        assert!(pos_memo < pos_post);
    }
}
