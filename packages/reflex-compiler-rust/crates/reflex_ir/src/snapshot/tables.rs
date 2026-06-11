//! Side tables on `Snapshot` for the cold / sparse data that doesn't
//! belong inline on every `NodeSnapshot`. See `super::mod` for the
//! `Snapshot` struct that owns these.

use std::collections::HashMap;

use smallvec::SmallVec;

use reflex_intern::Symbol;

use super::node::NodeIdx;

/// One memoized subtree body. The wrapper node in `nodes` references the
/// body via its slot here; stage 6 emits the body to a standalone module.
#[derive(Clone, Debug)]
pub struct MemoizeBody {
    /// Generated module name (e.g. `Box_passthrough_<hash>`).
    pub name: Symbol,
    /// `nodes` index of the root of the body subtree.
    pub root: NodeIdx,
    /// Identifying hash; matches the wrapper's `subtree_hash`.
    pub subtree_hash: u64,
    /// `"{ children }"` for passthroughs, `"()"` for snapshot bodies.
    pub signature: Symbol,
}

/// Backing storage for a `VarDataRef`. Each entry points into the dense
/// `var_hooks` / `var_imports` / `var_deps` / `var_components` Vecs via
/// `Range<u32>` slices so equal `VarData`s can dedupe to a single entry
/// in stage 4+.
#[derive(Clone, Debug, Default)]
pub struct VarDataEntry {
    pub hooks: std::ops::Range<u32>,
    pub imports: std::ops::Range<u32>,
    pub deps: std::ops::Range<u32>,
    pub components: std::ops::Range<u32>,
    /// Owning state class name; `Symbol::EMPTY` ⇔ no state binding.
    pub state: Symbol,
    /// Position bucket (mirrors `Hooks.HookPosition`); `u8::MAX` ⇔ none.
    pub position: u8,
}

/// Sparse per-node payloads for control-flow + text node kinds.
///
/// Stored separately because >99% of nodes are plain Elements / Fragments
/// that don't carry any of these. Looking up by `NodeIdx` from a HashMap
/// costs one probe per control-flow node, vs paying for an enum payload
/// on every node.
#[derive(Clone, Debug, Default)]
pub struct ControlFlowExtras {
    /// `Text.value`: pre-decoded literal text content (already JS-string
    /// escaped). Indexed by NodeIdx; absent slots emit empty string.
    pub text_value: HashMap<NodeIdx, Symbol>,
    /// `Cond.test`: pre-rendered JS expression for the condition.
    pub cond_test: HashMap<NodeIdx, Symbol>,
    /// `Foreach.iter`: pre-rendered JS expression for the iterable.
    pub foreach_iter: HashMap<NodeIdx, Symbol>,
    /// `Foreach` callback parameter names `(arg, index)` from the
    /// `IterTag` — the frozen body JSX references these names, so the
    /// emitters must use them rather than fixed placeholders.
    pub foreach_args: HashMap<NodeIdx, (Symbol, Symbol)>,
    /// `Match.value`: pre-rendered JS expression for the matched value.
    pub match_value: HashMap<NodeIdx, Symbol>,
    /// `Match.arms`: `(case_expr, body_node_idx)` pairs per match node.
    pub match_arms: HashMap<NodeIdx, SmallVec<[(Symbol, NodeIdx); 2]>>,
    /// `Match.default`: optional fallback body.
    pub match_default: HashMap<NodeIdx, NodeIdx>,
    /// `Expr.value`: pre-rendered JS expression for inline-rendered Vars.
    pub expr_value: HashMap<NodeIdx, Symbol>,
    /// Per-node ``add_custom_code`` MRO contributions (mirrors the chain
    /// half of ``_get_all_custom_code``; the node's own
    /// ``_get_custom_code`` lives in ``NodeSnapshot.custom_code``).
    pub custom_code_extra: HashMap<NodeIdx, SmallVec<[Symbol; 2]>>,
    /// Per-node spread props (``Tag.special_props``): pre-rendered Var
    /// expressions emitted as ``...{expr}`` after the keyed props.
    pub special_props: HashMap<NodeIdx, SmallVec<[Symbol; 1]>>,
    /// `Memoize.key`: memo wrapper key (React `key=` value).
    pub memo_key: HashMap<NodeIdx, Symbol>,
}

/// One app-wrap contribution. `sort_key` matches the legacy compile order
/// (`Component._get_app_wrap_components()` returns `(priority, name) →
/// component` dicts). After freeze close, `Snapshot.app_wraps` is deduped
/// on `(sort_key, name)`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct AppWrap {
    pub sort_key: i32,
    pub name: Symbol,
    /// `nodes` index of the wrap root subtree.
    pub root: NodeIdx,
}

/// Per-page metadata captured at freeze time. The route + title +
/// meta-tag set move into the snapshot in stage 4 (today they're still
/// piped through `compile_page_from_component`); the `schema_version`
/// pins the on-disk format the snapshot serializes to (when caching
/// lands in a later stage).
#[derive(Clone, Debug, Default)]
pub struct PageMeta {
    pub schema_version: u32,
    pub route: Symbol,
    pub title: Symbol,
    pub meta: Vec<(Symbol, Symbol)>,
}
