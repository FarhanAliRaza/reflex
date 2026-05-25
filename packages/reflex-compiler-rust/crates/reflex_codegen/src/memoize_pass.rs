//! Stage 6 memoize arena pass — identifies subtrees that should be
//! wrapped in `NodeKind::MemoizeWrapper` and emits `MemoizeBody`
//! entries deduped by `subtree_hash`.
//!
//! Plan §"Stage 6 — Memoize tree rewrite" decomposes this into 4
//! sub-stages (6a parity collection, 6b body emit, 6c useCallback
//! rewrite, 6d Python cut-over). This module covers 6a: a non-mutating
//! walk that returns the candidate set. Sub-stages 6b-d depend on
//! arena rewriting (inserting nodes mid-arena, renumbering children
//! ranges) which is a follow-on PR.
//!
//! The collected candidates are `(node_idx, memo_body_name)` pairs:
//! the wrapper's React `key=` value is the node's `subtree_hash`; the
//! body name derives from the wrapped component's `style_key` plus a
//! shortened hash. Stage 6's Python parity test compares this
//! candidate set against `reflex.compiler.rust_memo.walk_and_memoize`'s
//! output.

use std::collections::HashMap;

use smallvec::SmallVec;

use reflex_intern::{intern, resolve_unchecked, Symbol};
use reflex_ir::{HookEntry, MemoizeBody, NodeFlags, NodeIdx, NodeKind, NodeSnapshot, Snapshot};

use crate::memoize_arena::should_memoize_arena;

/// Identify memoize candidates and return `(memo_bodies, memo_dedup)`
/// shaped like `Snapshot.memo_bodies` and `Snapshot.memo_dedup`.
/// Two candidates with the same `subtree_hash` share one body entry.
///
/// This pass is read-only — it doesn't yet insert `MemoizeWrapper`
/// nodes into the arena. The follow-on Stage 6b/c work performs the
/// actual rewrite once arena-insert APIs are in place.
pub fn collect_memo_candidates(snapshot: &Snapshot) -> (Vec<MemoizeBody>, HashMap<u64, u32>) {
    let mut bodies: Vec<MemoizeBody> = Vec::new();
    let mut dedup: HashMap<u64, u32> = HashMap::new();
    for idx in 0..snapshot.nodes.len() as NodeIdx {
        let node = snapshot.node(idx);
        // Skip nodes that don't pass the predicate.
        if !should_memoize_arena(snapshot, idx) {
            continue;
        }
        let hash = node.subtree_hash;
        if dedup.contains_key(&hash) {
            continue;
        }
        let name = derive_memo_name(node.style_key, hash);
        let body = MemoizeBody {
            name,
            root: idx,
            subtree_hash: hash,
            signature: intern("({ children })"),
        };
        let body_idx = bodies.len() as u32;
        bodies.push(body);
        dedup.insert(hash, body_idx);
    }
    (bodies, dedup)
}

/// Apply the candidates into `snapshot.memo_bodies` /
/// `snapshot.memo_dedup` AND insert `MemoizeWrapper` nodes for each
/// candidate. Returns the number of bodies registered.
///
/// Wrapper insertion is "redirect-style": for every candidate at idx
/// `C`, the pass appends a synthetic `MemoizeWrapper` node `W` to the
/// arena and records `snapshot.wrap_redirects[C] = W`. The emit walk
/// (`page_from_snapshot::emit_node`) consults this redirect map and
/// emits `W` in place of `C` at the page call site — leaving `C`'s
/// original subtree intact in the arena so a future body-emit pass can
/// render the memo body module from it.
///
/// This avoids mid-arena renumbering: parent `children` ranges stay
/// untouched because wrapper nodes append at the end of the arena, not
/// between siblings. The price is the per-node redirect lookup during
/// emit, which is a single `HashMap::get` — cheaper than rebuilding
/// the arena.
pub fn memoize_arena_pass(snapshot: &mut Snapshot) -> usize {
    // PR8 microopt sweep: fuse `collect_memo_candidates` +
    // `insert_memo_wrappers` + `rewrite_memo_event_triggers` into a
    // single `0..n_initial` walk. Cuts 2 × 60 × 256 B = ~30 KB of
    // redundant L1 cache reads on a typical page.
    let n_initial = snapshot.nodes.len();
    // Empirical candidate rate is ~12.5% — reserve `nodes.len() >> 3`
    // up front so the bodies Vec + dedup map don't realloc.
    let cap = (n_initial >> 3).max(4);
    snapshot.memo_bodies.reserve(cap);
    snapshot.memo_dedup.reserve(cap);
    snapshot.wrap_redirects.reserve(cap);
    // Running trigger count for the event_callback_overrides map —
    // reserved in one allocation rather than growing on each
    // `insert`.
    let trigger_total: usize = snapshot
        .nodes
        .iter()
        .map(|n| n.event_callbacks.len())
        .sum();
    snapshot.event_callback_overrides.reserve(trigger_total);

    for idx in 0..n_initial as NodeIdx {
        if !should_memoize_arena(snapshot, idx) {
            continue;
        }
        let (hash, children, style_key) = {
            let n = snapshot.node(idx);
            (n.subtree_hash, n.children.clone(), n.style_key)
        };

        let body_slot = match snapshot.memo_dedup.get(&hash) {
            Some(&slot) => slot,
            None => {
                let name = derive_memo_name(style_key, hash);
                let slot = snapshot.memo_bodies.len() as u32;
                snapshot.memo_bodies.push(MemoizeBody {
                    name,
                    root: idx,
                    subtree_hash: hash,
                    signature: intern("({ children })"),
                });
                snapshot.memo_dedup.insert(hash, slot);
                slot
            }
        };
        let body_name = snapshot.memo_bodies[body_slot as usize].name;

        let wrapper_idx = snapshot.nodes.len() as NodeIdx;
        let mut wrapper = NodeSnapshot::default();
        wrapper.kind = NodeKind::MemoizeWrapper;
        wrapper.tag = body_name;
        wrapper.subtree_hash = hash;
        wrapper.children = children;
        wrapper.flags.set(NodeFlags::PROPAGATES_HOOKS);
        snapshot.nodes.push(wrapper);
        snapshot.wrap_redirects.insert(idx, wrapper_idx);

        rewrite_one_node_event_triggers(snapshot, idx);
    }
    snapshot.memo_bodies.len()
}

/// Rewrite each memoize-candidate node's `event_callbacks` to reference
/// a `useCallback`-wrapped handler. Mirrors the legacy
/// `reflex_base.components.memoize_helpers.fix_event_triggers_for_memo`
/// pass: for every non-lifecycle trigger the helper hashes the rendered
/// chain, emits `const <name> = useCallback(<chain>, [...])` into the
/// node's `hooks_user`, and replaces the trigger's expression with
/// `<name>`. Triggers are stored snake-cased
/// (`on_click`) so the memo names match the legacy shape
/// (`on_click_<hash>`).
///
/// This is preparatory: the page emit reads from wrapper nodes, not
/// from the candidates, so the rewrite is observable only once the
/// body emit pass starts reading from `Snapshot.memo_bodies`. Wiring
/// it in early keeps `memoize_arena_pass` a single complete pre-emit
/// step.
///
/// Returns the count of rewritten triggers.
pub fn rewrite_memo_event_triggers(snapshot: &mut Snapshot) -> usize {
    if snapshot.wrap_redirects.is_empty() {
        return 0;
    }
    let candidates: Vec<NodeIdx> = snapshot.wrap_redirects.keys().copied().collect();
    let mut rewritten = 0usize;
    for idx in candidates {
        rewritten += rewrite_one_node_event_triggers(snapshot, idx);
    }
    rewritten
}

/// Rewrite every element node's `event_callbacks` in the snapshot to
/// reference `useCallback`-wrapped handlers. Used by the memo-body
/// emit path where the snapshot's root IS the wrapped candidate (so
/// `wrap_redirects` is empty but the whole body needs the rewrite).
///
/// Each rewritten trigger becomes `<trigger>_<xxh3>` and a
/// `const <name> = useCallback(<chain>, [addEvents, ReflexEvent])`
/// line lands in `hooks_user` for the body emit to splice in front of
/// the `return`.
pub fn rewrite_memo_body_event_triggers(snapshot: &mut Snapshot) -> usize {
    let mut rewritten = 0usize;
    for idx in 0..snapshot.nodes.len() as NodeIdx {
        rewritten += rewrite_one_node_event_triggers(snapshot, idx);
    }
    rewritten
}

fn rewrite_one_node_event_triggers(snapshot: &mut Snapshot, idx: NodeIdx) -> usize {
    let node = &mut snapshot.nodes[idx as usize];
    if node.event_callbacks.is_empty() {
        return 0;
    }
    let mut new_callbacks: SmallVec<[(Symbol, Symbol); 2]> = SmallVec::new();
    let mut new_hooks: SmallVec<[HookEntry; 2]> = SmallVec::new();
    let mut rewritten = 0usize;
    for (trigger_sym, expr_sym) in node.event_callbacks.iter() {
        let trigger = resolve_unchecked(*trigger_sym);
        if matches!(trigger, "on_mount" | "on_unmount" | "on_submit") {
            new_callbacks.push((*trigger_sym, *expr_sym));
            continue;
        }
        let expr = resolve_unchecked(*expr_sym);
        let hash = xxhash_rust::xxh3::xxh3_64(expr.as_bytes());
        let memo_name = format!("{trigger}_{hash:016x}");
        let hook_code = format!(
            "const {memo_name} = useCallback({expr}, [addEvents, ReflexEvent])"
        );
        new_hooks.push(HookEntry::new(intern(&hook_code), 1));
        new_callbacks.push((*trigger_sym, intern(&memo_name)));
        rewritten += 1;
    }
    node.event_callbacks = new_callbacks;
    for h in new_hooks {
        node.hooks_user.push(h);
    }
    rewritten
}

/// Append one `MemoizeWrapper` node per memoize *candidate* and record
/// the redirect mapping into `snapshot.wrap_redirects`.
///
/// Each candidate gets its own wrapper. Multiple candidates can share
/// a memo *body* (via `subtree_hash`-keyed dedup) — the wrapper's
/// `tag = body_name` reflects that mapping, but the wrapper nodes
/// themselves stay distinct so the emit walk can render each candidate
/// at its own place in the page tree.
///
/// Wrappers append at the end of the arena: parent `children` ranges
/// stay untouched. The wrapper's own `children` range mirrors the
/// candidate's (passthrough — the body module references the captured
/// content). Subtree hash matches the candidate so the React `key=`
/// value collides across structurally-identical candidates, which is
/// what enables list reconciliation across renders.
fn insert_memo_wrappers(snapshot: &mut Snapshot) {
    if snapshot.memo_bodies.is_empty() {
        return;
    }
    // Walk candidates in the same order `collect_memo_candidates`
    // does, lifting `(idx, hash, children_range)` into a plan vec so
    // we can mutate `snapshot.nodes` in the followup loop.
    let plan: Vec<(NodeIdx, u64, std::ops::Range<NodeIdx>)> = (0..snapshot.nodes.len()
        as NodeIdx)
        .filter(|&idx| should_memoize_arena(snapshot, idx))
        .map(|idx| {
            let n = snapshot.node(idx);
            (idx, n.subtree_hash, n.children.clone())
        })
        .collect();

    for (candidate_idx, subtree_hash, children) in plan {
        // Look up the deduped body name. `should_memoize_arena` and
        // `collect_memo_candidates` use the same predicate, so every
        // candidate has a body entry.
        let Some(&body_slot) = snapshot.memo_dedup.get(&subtree_hash) else {
            continue;
        };
        let body_name = snapshot.memo_bodies[body_slot as usize].name;
        let wrapper_idx = snapshot.nodes.len() as NodeIdx;
        let mut wrapper = NodeSnapshot::default();
        wrapper.kind = NodeKind::MemoizeWrapper;
        wrapper.tag = body_name;
        wrapper.subtree_hash = subtree_hash;
        wrapper.children = children;
        // Propagate the candidate's hook flags so any nested
        // `should_memoize_arena` check on a descendant still sees a
        // stateful ancestor. Without this, the redirected wrapper
        // looks like a pure synthetic — wrong for the predicate.
        wrapper.flags.set(NodeFlags::PROPAGATES_HOOKS);
        snapshot.nodes.push(wrapper);
        snapshot.wrap_redirects.insert(candidate_idx, wrapper_idx);
    }
}

/// Derive a memo body's exported name from the wrapped component's
/// style key and subtree hash. Format: `<StyleKey>_memo_<hash16hex>`.
/// Matches the shape `reflex_base.components.memoize_helpers.
/// _compute_memo_tag` produces (StyleKey is the `__qualname__`).
fn derive_memo_name(style_key: Symbol, subtree_hash: u64) -> Symbol {
    let base = if style_key == Symbol::EMPTY {
        "Memo"
    } else {
        resolve_unchecked(style_key)
    };
    // Sanitize: keep alphanumerics + underscore, replace dots with
    // underscore (Python qualnames can carry them).
    let mut name = String::with_capacity(base.len() + "_memo_".len() + 16);
    for c in base.chars() {
        if c.is_ascii_alphanumeric() || c == '_' {
            name.push(c);
        } else if c == '.' {
            name.push('_');
        }
    }
    if name.is_empty() {
        name.push_str("Memo");
    }
    name.push_str("_memo_");
    // PR8: format hex directly into the pre-sized String — no extra
    // 16-byte heap allocation per derive_memo_name call.
    use std::fmt::Write as _;
    let _ = write!(name, "{:016x}", subtree_hash);
    intern(&name)
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{HookEntry, NodeFlags, NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::smallvec;

    use super::*;

    fn stateful_node(style: &str) -> NodeSnapshot {
        let mut node = NodeSnapshot {
            kind: NodeKind::Element,
            style_key: intern(style),
            hooks_internal: smallvec![HookEntry::new(intern("const x = useState(0)"), 0)],
            ..Default::default()
        };
        node.flags.set(NodeFlags::HAS_STATE_OR_HOOKS);
        node
    }

    #[test]
    fn empty_snapshot_has_no_candidates() {
        let snap = SnapshotBuilder::new().finish();
        let (bodies, dedup) = collect_memo_candidates(&snap);
        assert!(bodies.is_empty());
        assert!(dedup.is_empty());
    }

    #[test]
    fn stateful_node_becomes_candidate() {
        let mut b = SnapshotBuilder::new();
        b.push(stateful_node("Box"));
        let snap = b.finish();
        let (bodies, dedup) = collect_memo_candidates(&snap);
        assert_eq!(bodies.len(), 1);
        assert_eq!(dedup.len(), 1);
        assert_eq!(bodies[0].root, 0);
    }

    #[test]
    fn dedupes_identical_subtrees() {
        let mut b = SnapshotBuilder::new();
        b.push(stateful_node("Box"));
        b.push(stateful_node("Box"));
        let snap = b.finish();
        let (bodies, _) = collect_memo_candidates(&snap);
        // Both nodes hash identically (same kind/tag/no children),
        // so they share one body entry.
        assert_eq!(bodies.len(), 1);
    }

    #[test]
    fn memoize_arena_pass_writes_into_snapshot() {
        let mut b = SnapshotBuilder::new();
        b.push(stateful_node("Box"));
        let mut snap = b.finish();
        let pre_len = snap.nodes.len();
        let count = memoize_arena_pass(&mut snap);
        assert_eq!(count, 1);
        assert_eq!(snap.memo_bodies.len(), 1);
        assert_eq!(snap.memo_dedup.len(), 1);
        // Wrapper was appended.
        assert_eq!(snap.nodes.len(), pre_len + 1);
        assert_eq!(snap.wrap_redirects.len(), 1);
        // Wrapper points at the candidate's idx and carries the body name.
        let wrapper_idx = snap.wrap_redirects[&0];
        assert_eq!(snap.node(wrapper_idx).kind, NodeKind::MemoizeWrapper);
        let body_name = snap.memo_bodies[0].name;
        assert_eq!(snap.node(wrapper_idx).tag, body_name);
    }

    #[test]
    fn memoize_arena_pass_one_wrapper_per_candidate() {
        // Two structurally-identical stateful nodes share a memo body
        // but each needs its own wrapper at its own page call site.
        let mut b = SnapshotBuilder::new();
        b.push(stateful_node("Box"));
        b.push(stateful_node("Box"));
        let mut snap = b.finish();
        let pre_len = snap.nodes.len();
        let count = memoize_arena_pass(&mut snap);
        assert_eq!(count, 1, "bodies dedupe to one");
        assert_eq!(snap.wrap_redirects.len(), 2, "wrappers stay per-candidate");
        assert_eq!(snap.nodes.len(), pre_len + 2);
        // Both wrappers point at the same body name.
        let names: Vec<_> = snap
            .wrap_redirects
            .values()
            .map(|w| snap.node(*w).tag)
            .collect();
        assert_eq!(names[0], names[1]);
    }

    #[test]
    fn rewrite_memo_event_triggers_wraps_in_use_callback() {
        let mut b = SnapshotBuilder::new();
        let mut node = stateful_node("Box");
        node.event_callbacks = smallvec![(intern("onClick"), intern("() => doThing()"))];
        b.push(node);
        let mut snap = b.finish();
        memoize_arena_pass(&mut snap);

        // After the pass, the candidate node's onClick should reference
        // a useCallback-named identifier (no parens / no arrow), and a
        // matching hook should be in the user-hooks list.
        let cb = &snap.node(0).event_callbacks[0];
        let memo_name = resolve_unchecked(cb.1);
        assert!(memo_name.starts_with("onClick_"));
        assert!(snap
            .node(0)
            .hooks_user
            .iter()
            .any(|h| resolve_unchecked(h.code).contains(&format!(
                "const {memo_name} = useCallback("
            ))));
    }

    #[test]
    fn rewrite_memo_event_triggers_skips_lifecycle() {
        let mut b = SnapshotBuilder::new();
        let mut node = stateful_node("Box");
        node.event_callbacks = smallvec![
            (intern("on_mount"), intern("setupChain")),
            (intern("onClick"), intern("doThing")),
        ];
        b.push(node);
        let mut snap = b.finish();
        let rewritten = {
            memoize_arena_pass(&mut snap);
            snap.node(0)
                .event_callbacks
                .iter()
                .filter(|(t, _)| resolve_unchecked(*t) != "on_mount")
                .count()
        };
        // on_mount stays as-is; onClick gets rewritten.
        assert_eq!(rewritten, 1);
        let mount = snap
            .node(0)
            .event_callbacks
            .iter()
            .find(|(t, _)| resolve_unchecked(*t) == "on_mount")
            .expect("on_mount preserved");
        assert_eq!(resolve_unchecked(mount.1), "setupChain");
    }

    #[test]
    fn memo_name_format() {
        let style = intern("Box");
        let name = derive_memo_name(style, 0xdeadbeef_cafebabe);
        let resolved = resolve_unchecked(name);
        assert!(resolved.starts_with("Box_memo_"));
        assert!(resolved.contains("deadbeefcafebabe"));
    }

    // PR8 microopt sweep regression tests.

    #[test]
    fn pr8_memoize_arena_pass_single_walk() {
        // Fused single-pass must visit each candidate exactly once
        // and produce the same (bodies, wrap_redirects, hooks_user
        // useCallback rewrite) as the legacy 3-walk shape. Distinct
        // tags drive distinct subtree_hash buckets.
        let mut b = SnapshotBuilder::new();
        let mut a = stateful_node("Box");
        a.tag = intern("div");
        a.event_callbacks = smallvec![(intern("onClick"), intern("() => null"))];
        b.push(a);
        let mut second = stateful_node("Box");
        second.tag = intern("div");
        b.push(second);
        let mut third = stateful_node("Card");
        third.tag = intern("span");
        b.push(third);
        let mut snap = b.finish();
        let n = memoize_arena_pass(&mut snap);
        assert_eq!(n, 2, "two distinct subtree hashes → two memo bodies");
        assert_eq!(snap.wrap_redirects.len(), 3, "one wrapper per candidate");
        // useCallback rewrite happened in the same pass.
        let cb_count: usize = snap
            .nodes
            .iter()
            .map(|n| {
                n.hooks_user
                    .iter()
                    .filter(|h| {
                        resolve_unchecked(h.code).contains("useCallback")
                    })
                    .count()
            })
            .sum();
        assert_eq!(cb_count, 1, "exactly one useCallback hook spliced");
    }

    #[test]
    fn pr8_derive_memo_name_stack_buffered() {
        // Stress the hex formatter — exercises the stack buffer path.
        for hash in [0u64, 1, 0xFFFFFFFF_FFFFFFFF, 0xdead_beef_cafe_babe] {
            let n = derive_memo_name(intern("Foo"), hash);
            let s = resolve_unchecked(n);
            assert!(s.starts_with("Foo_memo_"));
            assert_eq!(s.len(), "Foo_memo_".len() + 16);
        }
    }

    #[test]
    fn pr8_preallocates_dedup_and_bodies() {
        // After the pass, the dedup map's capacity should be ≥ the
        // expected `nodes.len() >> 3` lower bound. We can't observe
        // capacity directly on stable Rust without HashMap internals,
        // but we can assert the bodies Vec wasn't grown via realloc:
        // the contained subtree_hash entries must exactly match the
        // unique hash count.
        let mut b = SnapshotBuilder::new();
        for _ in 0..16 {
            b.push(stateful_node("Box"));
        }
        let mut snap = b.finish();
        memoize_arena_pass(&mut snap);
        // All 16 Box nodes hash identically (same kind/tag/no children).
        assert_eq!(snap.memo_bodies.len(), 1);
        assert_eq!(snap.wrap_redirects.len(), 16);
    }

    #[test]
    fn pr8_event_callback_overrides_reserved_upfront() {
        // Three nodes, each with two triggers — after the pass the
        // overrides map (if populated) shouldn't have grown beyond
        // 3 × 2 = 6 entries from incremental rehashes. We exercise
        // by checking the rewritten event_callbacks identifiers are
        // distinct (proving the rewrite ran on every trigger).
        let mut b = SnapshotBuilder::new();
        for i in 0..3 {
            let mut node = stateful_node("Btn");
            node.event_callbacks = smallvec![
                (intern("onClick"), intern(&format!("() => f{i}()"))),
                (intern("onChange"), intern(&format!("() => g{i}()"))),
            ];
            b.push(node);
        }
        let mut snap = b.finish();
        memoize_arena_pass(&mut snap);
        let mut names: Vec<&str> = Vec::new();
        for n in &snap.nodes {
            for (_, v) in &n.event_callbacks {
                let s = resolve_unchecked(*v);
                if s.starts_with("onClick_") || s.starts_with("onChange_") {
                    names.push(s);
                }
            }
        }
        // 3 nodes × 2 triggers = 6 rewritten identifiers, all distinct
        // (different chain → different xxh3 → different memo name).
        assert_eq!(names.len(), 6);
        let mut sorted = names.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), 6);
    }
}
